from flask import Flask, request
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)

EMAIL = "amitnplindia21@gmail.com"
PASSWORD = "ctmweznzewgtypup"  # App Password without spaces

@app.route('/send-sms', methods=['POST'])
def send_sms():
    raw_data = request.get_data(as_text=True)
    print("Raw data received:", raw_data)  # Debug line
    data = request.json
    message = data.get('message')
    to_email = "divyaforself@gmail.com"

    msg = MIMEText(message)
    msg['Subject'] = 'SMS Alert'
    msg['From'] = EMAIL
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL, PASSWORD)
            server.send_message(msg)
        return {"status": "Email sent"}
    except Exception as e:
        return {"status": f"Failed to send email: {str(e)}"}, 500

if __name__ == '__main__':
    app.run(debug=True)