import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from tracker.models import PriceRecord


class LSTMModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=50, batch_first=True)
        self.fc = nn.Linear(50, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])


class PriceLSTM(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm1 = nn.LSTM(input_size=1, hidden_size=64, batch_first=True)
        self.lstm2 = nn.LSTM(input_size=64, hidden_size=32, batch_first=True)
        self.fc1 = nn.Linear(32, 16)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(16, 1)

    def forward(self, x):
        out, _ = self.lstm1(x)
        out, _ = self.lstm2(out)
        out = self.relu(self.fc1(out[:, -1, :]))
        return self.fc2(out)


def train_lstm(product_id):
    records = PriceRecord.objects.filter(product_id=product_id).order_by("recorded_at")
    prices = [float(r.price) for r in records]

    if len(prices) < 10:
        return None

    prices = np.array(prices).reshape(-1, 1)

    scaler = MinMaxScaler()
    prices_scaled = scaler.fit_transform(prices)

    X, y = [], []
    for i in range(5, len(prices_scaled)):
        X.append(prices_scaled[i-5:i])
        y.append(prices_scaled[i])

    X, y = np.array(X), np.array(y)

    split = int(0.8 * len(X))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    X_train_t = torch.tensor(X_train, dtype=torch.float32)
    y_train_t = torch.tensor(y_train, dtype=torch.float32)

    model = LSTMModel()
    optimizer = torch.optim.Adam(model.parameters())
    loss_fn = nn.MSELoss()

    model.train()
    for _ in range(3):
        optimizer.zero_grad()
        output = model(X_train_t)
        loss = loss_fn(output, y_train_t)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        X_test_t = torch.tensor(X_test, dtype=torch.float32)
        predictions = model(X_test_t).numpy()

    y_test = y_test.flatten()
    predictions = predictions.flatten()

    mae = mean_absolute_error(y_test, predictions)
    mse = mean_squared_error(y_test, predictions)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, predictions)

    y_safe = np.where(y_test == 0, 1, y_test)
    mape = np.mean(np.abs((y_test - predictions) / y_safe)) * 100

    print("\n📊 MODEL PERFORMANCE METRICS")
    print("================================")
    print(f"MAE  : {mae:.4f}")
    print(f"RMSE : {rmse:.4f}")
    print(f"MSE  : {mse:.4f}")
    print(f"R2   : {r2:.4f}")
    print(f"MAPE : {mape:.2f}%")
    print("================================\n")

    return model, scaler, prices_scaled


def predict_prices(model, X_test, y_test):
    model.eval()
    with torch.no_grad():
        X_test_t = torch.tensor(X_test, dtype=torch.float32)
        predictions = model(X_test_t).numpy()

    y_true = y_test
    y_pred = predictions

    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_true, y_pred)
    mape = np.mean(np.abs((y_true - y_pred) / y_true)) * 100

    print("MAE:", mae)
    print("RMSE:", rmse)
    print("R2:", r2)
    print("MAPE:", mape)

    return predictions
