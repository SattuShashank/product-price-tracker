import os
import numpy as np
import joblib
import torch

from django.core.management.base import BaseCommand
from tracker.models import PriceRecord
from tracker.ml.lstm_model import PriceLSTM


class Command(BaseCommand):
    help = "Predict next price for a product"

    def add_arguments(self, parser):
        parser.add_argument("--product-id", type=int, required=True)

    def handle(self, *args, **options):
        product_id = options["product_id"]

        model_path = f"tracker/ml_models/price_lstm_product_{product_id}.pt"
        scaler_path = f"tracker/ml_models/price_scaler_product_{product_id}.pkl"

        if not os.path.exists(model_path):
            self.stdout.write("❌ Model not found")
            return

        checkpoint = torch.load(model_path, weights_only=True)
        model = PriceLSTM()
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()

        scaler = joblib.load(scaler_path)

        qs = (
            PriceRecord.objects.filter(product_id=product_id)
            .order_by("recorded_at")
            .values_list("price", flat=True)
        )

        prices = list(qs)[-30:]

        if len(prices) < 30:
            self.stdout.write("❌ Not enough data")
            return

        prices = np.array(prices, dtype=np.float32).reshape(-1, 1)
        scaled = scaler.transform(prices)

        X = torch.tensor(scaled.reshape(1, 30, 1), dtype=torch.float32)

        with torch.no_grad():
            pred = model(X).numpy()

        predicted_price = scaler.inverse_transform(pred)[0][0]

        self.stdout.write(f"📈 Predicted next price: {predicted_price:.2f}")
