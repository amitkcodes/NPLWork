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
    to_emails = data.get('to_emails')  # Expecting a list of email addresses

    if not isinstance(to_emails, list):
        return {"status": "Error: 'to_emails' must be a list of email addresses"}, 400

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL, PASSWORD)
            for email in to_emails:
                msg = MIMEText(message)
                msg['Subject'] = 'SMS Alert'
                msg['From'] = EMAIL
                msg['To'] = email
                server.send_message(msg)
        return {"status": f"Email sent to {len(to_emails)} recipients"}
    except Exception as e:
        return {"status": f"Failed to send email: {str(e)}"}, 500

if __name__ == '__main__':
    app.run(debug=True)