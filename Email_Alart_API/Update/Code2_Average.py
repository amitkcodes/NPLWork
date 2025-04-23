# I want to avoid multiper no server responce between 1 hours
from flask import Flask, request
import smtplib
from email.mime.text import MIMEText
import ntplib
import csv
from datetime import datetime
import time
import logging
import threading
import requests
import json
import os

# Flask app setup
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

# Logging setup for NTP
log_file = os.path.join(os.getcwd(), 'ntp_data.log')
logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to send alert via Flask API
def send_alert(message, to_emails):
    url = 'http://localhost:5000/send-sms'  # Flask app endpoint
    payload = {
        'message': message,
        'to_emails': to_emails
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        response.raise_for_status()
        logging.info(f"Alert sent: {response.json()}")
    except requests.RequestException as e:
        logging.error(f"Failed to send alert: {e}")

# Function to query NTP server and process response
def get_offset_and_delay_from_ntp(server, alert_emails):
    ntp_client = ntplib.NTPClient()
    try:
        response = ntp_client.request(server, timeout=10)
        offset_in_sec = response.offset
        delay_in_sec = response.delay
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data = {'Time': current_time, 'Server': server, 'Offset': offset_in_sec, 'Delay': delay_in_sec, 'Offset_Diff_From_Avg': 0, 'Sign': ''}
        print(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}, Time: {current_time}")
        logging.info(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}")
        if abs(offset_in_sec) > 0.5 or (delay_in_sec > 0.2 and delay_in_sec > 0):  # Adjusted threshold
            alert_message = f"NTP Server Alert\nServer: {server}\nOffset: {offset_in_sec:.6f} seconds\nDelay: {delay_in_sec:.6f} seconds\nTime: {current_time}"
            send_alert(alert_message, alert_emails)
        return offset_in_sec, delay_in_sec, data
    except ntplib.NTPException as e:
        logging.error(f"Error querying NTP server {server}: {e}")
        print(f"Error querying NTP server {server}: {e}")  # Added for console visibility
        alert_message = f"Error querying NTP server {server}: {str(e)}"
        send_alert(alert_message, alert_emails)
        data = {'Time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'Server': server, 'Offset': 0, 'Delay': 0, 'Offset_Diff_From_Avg': 0, 'Sign': ''}
        return 0, 0, data
    except Exception as e:
        logging.error(f"Unexpected error querying NTP server {server}: {e}")
        print(f"Unexpected error querying NTP server {server}: {e}")
        alert_message = f"Unexpected error querying NTP server {server}: {str(e)}"
        send_alert(alert_message, alert_emails)
        data = {'Time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'Server': server, 'Offset': 0, 'Delay': 0, 'Offset_Diff_From_Avg': 0, 'Sign': ''}
        return 0, 0, data

# Function to save data to a single CSV file
def save_to_csv(data):
    filename = os.path.join(os.getcwd(), 'ntp_data.csv')  # Save in current working directory
    try:
        with open(filename, 'a', newline='') as csvfile:
            fieldnames = ['Time', 'Server', 'Offset', 'Delay', 'Offset_Diff_From_Avg', 'Sign']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if csvfile.tell() == 0:  # Write header if file is empty
                writer.writeheader()
            # Convert current_time to UTC ISO format
            data['Time'] = datetime.strptime(data['Time'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%SZ')
            writer.writerow(data)
    except Exception as e:
        logging.error(f"Error saving data to {filename}: {e}")

# Function to fetch data from all servers and calculate average offset
def fetch_data_from_servers(ntp_servers, alert_emails):
    results = []
    threads = []
    for server in ntp_servers:
        thread = threading.Thread(target=lambda s=server: results.append((s, get_offset_and_delay_from_ntp(s, alert_emails))))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    
    # Calculate average offset for successful queries
    valid_offsets = [(server, offset) for server, (offset, _, _) in results if offset != 0]
    if valid_offsets:
        offsets = [offset for _, offset in valid_offsets]
        avg_offset = sum(offsets) / len(offsets)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds, Time: {current_time}")
        logging.info(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds")
        
        # Save individual server data with differences
        for server, (offset, delay, data) in results:
            if offset != 0:
                diff = offset - avg_offset
                sign = '+' if diff >= 0 else '-'
                data['Offset_Diff_From_Avg'] = diff
                data['Sign'] = sign
                print(f"Server: {server}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                logging.info(f"Server: {server}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
            save_to_csv(data)
        
        # Save average to CSV
        avg_data = {
            'Time': current_time,
            'Server': 'Average',
            'Offset': avg_offset,
            'Delay': 0,  # Delay not averaged
            'Offset_Diff_From_Avg': 0,
            'Sign': 'N/A'
        }
        save_to_csv(avg_data)
    else:
        # Save failed server data even if no average
        for server, (_, _, data) in results:
            save_to_csv(data)
        print("No valid offsets to calculate average.")
        logging.info("No valid offsets to calculate average.")

# Function to run NTP monitoring
def run_ntp_monitoring(ntp_servers, alert_emails):
    try:
        while True:
            fetch_data_from_servers(ntp_servers, alert_emails)
            print("Waiting for 5 minutes before collecting data again...")
            time.sleep(600)
            print("Resuming data collection...")
    except KeyboardInterrupt:
        logging.info("Script interrupted. Exiting gracefully...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

# Main execution
if __name__ == '__main__':
    # List of NTP servers
    ntp_servers = [
        '157.20.66.8', 'ntp.doca.gov.in', 'samay1.nic.in', 'samay2.nic.in',
        '192.168.251.12', '192.168.251.14', '192.168.251.15', '192.168.251.18',
        '192.168.251.21', '192.168.251.22', '192.168.251.24', '192.168.251.30',
        '192.168.251.32', '192.168.251.33', '192.168.251.38', '192.168.251.39'
    ]
    
    # List of email addresses for alerts
    alert_emails = ['amitnplindia21@gmail.com',]# 'amitkaushik337@gmail.com']
    
    # Start NTP monitoring in a separate thread
    ntp_thread = threading.Thread(target=run_ntp_monitoring, args=(ntp_servers, alert_emails))
    ntp_thread.daemon = True  # Daemonize to stop with main thread
    ntp_thread.start()
    
    # Start Flask app
    app.run(debug=True, use_reloader=False)  # use_reloader=False to prevent duplicate threads in debug mode