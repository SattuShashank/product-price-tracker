from django.core.mail import send_mail

def send_price_alert(email, product, current_price, predicted_price):
    subject = f"🔥 Price Drop Alert: {product.name}"

    message = f"""
Product: {product.name}

Current Price: ₹{current_price}
Predicted Price: ₹{predicted_price}

👉 Recommendation: BUY NOW

- Price Tracker AI
"""

    send_mail(
        subject,
        message,
        None,
        [email],
        fail_silently=False,
    )