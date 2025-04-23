import threading
from flask import Flask, request
import smtplib
from email.mime.text import MIMEText
import ntplib
import csv
from datetime import datetime
import time
import logging
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor
import requests
import json
import os

# Flask app setup
app = Flask(__name__)

EMAIL = "amitnplindia21@gmail.com"
PASSWORD = "ctmweznzewgtypup"  # App Password

# Alert rate-limiting
last_alert_time = {}

@app.route('/send-sms', methods=['POST'])
def send_sms():
    raw_data = request.get_data(as_text=True)
    print("Raw data received:", raw_data)
    data = request.json
    message = data.get('message')
    to_emails = data.get('to_emails')

    if not isinstance(to_emails, list):
        return {"status": "Error: 'to_emails' must be a list"}, 400

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

# Logging setup
log_file = os.path.join(os.getcwd(), 'ntp_data.log')
handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to send alert via Flask API with rate-limiting
def send_alert(message, to_emails):
    server = message.split("Server: ")[1].split("\n")[0] if "Server: " in message else "unknown"
    current_time = time.time()
    if server not in last_alert_time or current_time - last_alert_time[server] > 3600:  # 1 hour
        last_alert_time[server] = current_time
        url = 'http://localhost:5000/send-sms'
        payload = {'message': message, 'to_emails': to_emails}
        headers = {'Content-Type': 'application/json'}
        try:
            response = requests.post(url, data=json.dumps(payload), headers=headers)
            response.raise_for_status()
            logging.info(f"Alert sent: {response.json()}")
        except requests.RequestException as e:
            logging.error(f"Failed to send alert: {e}")

# Function to query NTP server
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
        if delay_in_sec < 0:
            logging.warning(f"Negative delay detected for {server}: {delay_in_sec}")
        elif abs(offset_in_sec) > 0.5 or delay_in_sec > 0.2:
            alert_message = f"NTP Server Alert\nServer: {server}\nOffset: {offset_in_sec:.6f} seconds\nDelay: {delay_in_sec:.6f} seconds\nTime: {current_time}"
            send_alert(alert_message, alert_emails)
        return offset_in_sec, delay_in_sec, data
    except ntplib.NTPException as e:
        logging.error(f"Error querying NTP server {server}: {e}")
        print(f"Error querying NTP server {server}: {e}")
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

# Function to save data to CSV
def save_to_csv(data):
    filename = os.path.join(os.getcwd(), 'ntp_data.csv')
    try:
        with open(filename, 'a', newline='') as csvfile:
            fieldnames = ['Time', 'Server', 'Offset', 'Delay', 'Offset_Diff_From_Avg', 'Sign']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if csvfile.tell() == 0:
                writer.writeheader()
            data['Time'] = datetime.strptime(data['Time'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%SZ')
            writer.writerow(data)
    except Exception as e:
        logging.error(f"Error saving data to {filename}: {e}")

# Function to fetch data from all servers
def fetch_data_from_servers(ntp_servers, alert_emails):
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_offset_and_delay_from_ntp, server, alert_emails) for server in ntp_servers]
        for future in futures:
            results.append((None, future.result()))
    
    valid_offsets = [(offset, data) for _, (offset, _, data) in results if offset != 0]
    if valid_offsets:
        offsets = [offset for offset, _ in valid_offsets]
        avg_offset = sum(offsets) / len(offsets)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds, Time: {current_time}")
        logging.info(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds")
        
        for _, (offset, delay, data) in results:
            if offset != 0:
                diff = offset - avg_offset
                sign = '+' if diff >= 0 else '-'
                data['Offset_Diff_From_Avg'] = diff
                data['Sign'] = sign
                print(f"Server: {data['Server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                logging.info(f"Server: {data['Server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                # Check if Offset_Diff_From_Avg exceeds 0.05 ms (0.000005 seconds)
                if abs(diff) > 0.001:
                    alert_message = (
                        f"NTP Server Offset Deviation Alert\n"
                        f"Server: {data['Server']}\n"
                        f"Offset: {offset:.6f} seconds\n"
                        f"Delay: {delay:.6f} seconds\n"
                        f"Offset Diff from Avg: {diff:.6f} seconds\n"
                        f"Sign: {sign}\n"
                        f"Time: {current_time}"
                    )
                    send_alert(alert_message, alert_emails)
            save_to_csv(data)
        
        avg_data = {
            'Time': current_time,
            'Server': 'Average',
            'Offset': avg_offset,
            'Delay': 0,
            'Offset_Diff_From_Avg': 0,
            'Sign': 'N/A'
        }
        save_to_csv(avg_data)
    else:
        for _, (_, _, data) in results:
            save_to_csv(data)
        print("No valid offsets to calculate average.")
        logging.info("No valid offsets to calculate average.")

# Function to run NTP monitoring
def run_ntp_monitoring(ntp_servers, alert_emails):
    try:
        while True:
            fetch_data_from_servers(ntp_servers, alert_emails)
            print("Waiting for 5 minutes before collecting data again...")
            time.sleep(300)
            print("Resuming data collection...")
    except KeyboardInterrupt:
        logging.info("Script interrupted. Exiting gracefully...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

# Main execution
if __name__ == '__main__':
    ntp_servers = [
        '157.20.66.8', 'ntp.doca.gov.in', 'samay1.nic.in', 'samay2.nic.in',
        '192.168.251.12', '192.168.251.14', '192.168.251.15', '192.168.251.18',
        '192.168.251.21', '192.168.251.22', '192.168.251.24', '192.168.251.30',
        '192.168.251.32', '192.168.251.33', '192.168.251.38', '192.168.251.39'
    ]
    
    alert_emails = ['amitnplindia21@gmail.com',]# 'amitkaushik337@gmail.com']
    
    ntp_thread = threading.Thread(target=run_ntp_monitoring, args=(ntp_servers, alert_emails))
    ntp_thread.daemon = True
    ntp_thread.start()
    
    app.run(debug=True, use_reloader=False)