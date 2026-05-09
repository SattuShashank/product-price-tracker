import os
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from sklearn.preprocessing import MinMaxScaler

from tracker.models import PriceRecord
from tracker.ml.lstm_model import PriceLSTM


class Command(BaseCommand):
    help = "Train an LSTM model on product price history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-id",
            type=int,
            default=None,
            help="Train on a specific product ID. If omitted, uses the product with the most price records.",
        )
        parser.add_argument(
            "--seq-len",
            type=int,
            default=30,
            help="Number of past price points used to predict the next one.",
        )
        parser.add_argument(
            "--epochs",
            type=int,
            default=20,
            help="Training epochs.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=32,
            help="Training batch size.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="tracker/ml_models",
            help="Where to save the model and scaler.",
        )

    def handle(self, *args, **options):
        seq_len = options["seq_len"]
        epochs = options["epochs"]
        batch_size = options["batch_size"]
        output_dir = options["output_dir"]
        product_id = options["product_id"]

        if product_id is None:
            top_product = (
                PriceRecord.objects.values("product_id")
                .annotate(total=Count("id"))
                .order_by("-total")
                .first()
            )
            if not top_product:
                raise CommandError("No PriceRecord data found in the database.")
            product_id = top_product["product_id"]

        qs = (
            PriceRecord.objects.filter(product_id=product_id)
            .order_by("recorded_at")
            .values("recorded_at", "price")
        )

        df = pd.DataFrame(list(qs))
        if df.empty:
            raise CommandError(f"No price history found for product_id={product_id}.")

        df["recorded_at"] = pd.to_datetime(df["recorded_at"])
        df["price"] = df["price"].astype(float)
        df = df.sort_values("recorded_at").reset_index(drop=True)

        if len(df) < seq_len + 1:
            raise CommandError(
                f"Not enough data for product_id={product_id}. "
                f"Need at least {seq_len + 1} records, found {len(df)}."
            )

        prices = df[["price"]].values

        scaler = MinMaxScaler()
        scaled_prices = scaler.fit_transform(prices)

        X, y = [], []
        for i in range(len(scaled_prices) - seq_len):
            X.append(scaled_prices[i : i + seq_len])
            y.append(scaled_prices[i + seq_len])

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        split_index = int(len(X) * 0.8)
        if split_index < 1 or split_index >= len(X):
            raise CommandError("Not enough samples after sequence creation to split train/validation sets.")

        X_train, X_val = X[:split_index], X[split_index:]
        y_train, y_val = y[:split_index], y[split_index:]

        X_train_t = torch.tensor(X_train)
        y_train_t = torch.tensor(y_train)
        X_val_t = torch.tensor(X_val)
        y_val_t = torch.tensor(y_val)

        dataset = TensorDataset(X_train_t, y_train_t)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        model = PriceLSTM()
        optimizer = torch.optim.Adam(model.parameters())
        loss_fn = nn.MSELoss()

        best_val_loss = float("inf")
        patience_counter = 0
        patience = 3
        best_state = None
        final_train_loss = 0.0
        final_val_loss = 0.0

        for epoch in range(epochs):
            model.train()
            batch_losses = []
            for X_batch, y_batch in loader:
                optimizer.zero_grad()
                output = model(X_batch)
                loss = loss_fn(output, y_batch)
                loss.backward()
                optimizer.step()
                batch_losses.append(loss.item())

            model.eval()
            with torch.no_grad():
                val_output = model(X_val_t)
                val_loss = loss_fn(val_output, y_val_t).item()

            train_loss = sum(batch_losses) / len(batch_losses)
            final_train_loss = train_loss
            final_val_loss = val_loss

            self.stdout.write(
                f"Epoch {epoch + 1}/{epochs} - loss: {train_loss:.6f} - val_loss: {val_loss:.6f}"
            )

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    self.stdout.write("Early stopping triggered.")
                    break

        if best_state:
            model.load_state_dict(best_state)

        os.makedirs(output_dir, exist_ok=True)

        model_path = os.path.join(output_dir, f"price_lstm_product_{product_id}.pt")
        scaler_path = os.path.join(output_dir, f"price_scaler_product_{product_id}.pkl")

        torch.save({"state_dict": model.state_dict()}, model_path)
        joblib.dump(scaler, scaler_path)

        self.stdout.write(self.style.SUCCESS("Training completed successfully."))
        self.stdout.write(f"Product ID: {product_id}")
        self.stdout.write(f"Model saved to: {model_path}")
        self.stdout.write(f"Scaler saved to: {scaler_path}")
        self.stdout.write(f"Final train loss: {final_train_loss:.6f}")
        self.stdout.write(f"Final val loss: {final_val_loss:.6f}")
