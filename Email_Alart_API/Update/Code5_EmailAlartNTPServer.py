# Copyright (c) 2025 Amit Kaushik
# Idea by: Divya Singh Yadav
# Code written by: Amit Kaushik
# All rights reserved.
#
# -------------------------------------Preserved Functionality:------------------------------------
# Consecutive Checks: The script tracks failures and deviations across monitoring cycles (every 5 minutes).
# If a server fails 3 times in a row (15 minutes) or has high deviations 3 times in a row, an alert is sent.
# Reset Logic: Counts reset after an alert or when the condition is not met
# (e.g., successful query or deviation ≤ 0.01 seconds), preventing false positives.
# - Alerting after 3 consecutive no-response failures.
# - Alerting after 3 consecutive deviations > 0.01 seconds (10 ms).
# - Alerts for abs(offset_in_sec) > 0.5 or delay_in_sec > 0.2 (immediate, no consecutive check).
# - Rate-limiting (1 alert/hour/server).
# - Log rotation (10 MB, 5 backups).
# - CSV saving to ntp_data.csv.
# - Thread pool with 4 workers.
# - 5-minute monitoring interval.

#---------------------------------------Import Section-------------------------------------
import threading  # For running NTP monitoring in a separate thread
from flask import Flask, request  # For creating a web API to send alerts
import smtplib  # For sending emails via Gmail SMTP
from email.mime.text import MIMEText  # For formatting email messages
import ntplib  # For querying NTP servers
import csv  # For saving data to CSV files
from datetime import datetime  # For handling timestamps
import time  # For handling delays and rate-limiting
import logging  # For logging events to a file
from logging.handlers import RotatingFileHandler  # For rotating log files
from concurrent.futures import ThreadPoolExecutor  # For concurrent NTP queries
import requests  # For sending HTTP requests to the Flask API
import json  # For handling JSON data
import os  # For handling file paths

# Initialize Flask app for handling API requests
app = Flask(__name__)

# Gmail credentials for sending email alerts
EMAIL = "amitnplindia21@gmail.com"
PASSWORD = "ctmweznzewgtypup"  # App-specific password for Gmail SMTP

# Dictionary to track the last alert time for each server (for rate-limiting)
last_alert_time = {}

# Dictionaries to track consecutive failures and deviations for each server
consecutive_failures = {}  # Tracks consecutive no-response counts
consecutive_deviations = {}  # Tracks consecutive high deviation counts

# --------------------------------------------Flask endpoint to handle POST requests for sending email alerts-----------------------------------
@app.route('/send-sms', methods=['POST'])
def send_sms():
    # Get raw request data for debugging
    raw_data = request.get_data(as_text=True)
    print("Raw data received:", raw_data)
    
    # Parse JSON payload from the request
    data = request.json
    message = data.get('message')  # Extract message content
    to_emails = data.get('to_emails')  # Extract list of recipient emails

    # Validate that to_emails is a list
    if not isinstance(to_emails, list):
        return {"status": "Error: 'to_emails' must be a list"}, 400

    try:
        # Connect to Gmail SMTP server using SSL
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL, PASSWORD)  # Authenticate with Gmail
            # Send email to each recipient
            for email in to_emails:
                msg = MIMEText(message)  # Create email message
                msg['Subject'] = 'SMS Alert'  # Set email subject
                msg['From'] = EMAIL  # Set sender
                msg['To'] = email  # Set recipient
                server.send_message(msg)  # Send email
        # Return success response
        return {"status": f"Email sent to {len(to_emails)} recipients"}
    except Exception as e:
        # Return error response if email sending fails
        return {"status": f"Failed to send email: {str(e)}"}, 500

# -----------------------------------------Setup logging with rotation to manage log file size--------------------------------------
log_file = os.path.join(os.getcwd(), 'ntp_data.log')  # Log file path
handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)  # Rotate logs at 10 MB, keep 5 backups
logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # Configure logging format

# -----------------------------------------Function to send alerts via Flask API with rate-limiting----------------------------------
def send_alert(message, to_emails):
    # Extract server name from the message for rate-limiting
    server = message.split("Server: ")[1].split("\n")[0] if "Server: " in message else "unknown"
    current_time = time.time()
    
    # Check if alert is allowed (1-hour rate limit per server)
    if server not in last_alert_time or current_time - last_alert_time[server] > 3600:
        last_alert_time[server] = current_time  # Update last alert time
        url = 'http://localhost:5000/send-sms'  # Flask API endpoint
        payload = {'message': message, 'to_emails': to_emails}  # Prepare payload
        headers = {'Content-Type': 'application/json'}  # Set JSON content type
        try:
            # Send POST request to Flask API
            response = requests.post(url, data=json.dumps(payload), headers=headers)
            response.raise_for_status()  # Raise exception for HTTP errors
            logging.info(f"Alert sent: {response.json()}")  # Log success
        except requests.RequestException as e:
            # Log error if alert sending fails
            logging.error(f"Failed to send alert: {e}")

# ----------------------------------------------Function to query an NTP server for offset and delay--------------------------------------
def get_offset_and_delay_from_ntp(server, alert_emails):
    ntp_client = ntplib.NTPClient()  # Initialize NTP client
    try:
        # Query NTP server with a 10-second timeout
        response = ntp_client.request(server, timeout=10)
        offset_in_sec = response.offset  # Get time offset (seconds)
        delay_in_sec = response.delay  # Get round-trip delay (seconds)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Get current timestamp
        
        # Reset failure count for this server since query succeeded
        consecutive_failures[server] = 0
        
        # Prepare data dictionary for logging and CSV
        data = {
            'Time': current_time,
            'Server': server,
            'Offset': offset_in_sec,
            'Delay': delay_in_sec,
            'Offset_Diff_From_Avg': 0,
            'Sign': ''
        }
        
        # Log and print server response
        print(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}, Time: {current_time}")
        logging.info(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}")
        
        # Check for negative delay (invalid, log warning but no alert)
        if delay_in_sec < 0:
            logging.warning(f"Negative delay detected for {server}: {delay_in_sec}")
        # Check for large offset (>0.5s) or delay (>0.2s) and send alert
        elif abs(offset_in_sec) > 0.5 or delay_in_sec > 0.2:
            alert_message = (
                f"NTP Server Alert\n"
                f"Server: {server}\n"
                f"Offset: {offset_in_sec:.6f} seconds\n"
                f"Delay: {delay_in_sec:.6f} seconds\n"
                f"Time: {current_time}"
            )
            send_alert(alert_message, alert_emails)
        
        return offset_in_sec, delay_in_sec, data
    except (ntplib.NTPException, Exception) as e:
        # Handle both NTP-specific and unexpected errors
        logging.error(f"Error querying NTP server {server}: {e}")
        print(f"Error querying NTP server {server}: {e}")
        
        # Increment failure count
        consecutive_failures[server] = consecutive_failures.get(server, 0) + 1
        
        # Send alert only after 3 consecutive failures
        if consecutive_failures[server] >= 3:
            alert_message = (
                f"NTP Server No Response Alert\n"
                f"Server: {server}\n"
                f"Error: Failed to respond 3 consecutive times\n"
                f"Last Error: {str(e)}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_alert(alert_message, alert_emails)
            consecutive_failures[server] = 0  # Reset after alerting
        
        # Return default data for failed queries
        data = {
            'Time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Server': server,
            'Offset': 0,
            'Delay': 0,
            'Offset_Diff_From_Avg': 0,
            'Sign': ''
        }
        return 0, 0, data

# ----------------------------------------------Function to save NTP data to a CSV file--------------------------------------------
def save_to_csv(data):
    filename = os.path.join(os.getcwd(), 'ntp_data.csv')  # CSV file path
    try:
        with open(filename, 'a', newline='') as csvfile:  # Append mode
            fieldnames = ['Time', 'Server', 'Offset', 'Delay', 'Offset_Diff_From_Avg', 'Sign']  # CSV columns
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            # Write header if file is empty
            if csvfile.tell() == 0:
                writer.writeheader()
            # Convert timestamp to ISO format
            data['Time'] = datetime.strptime(data['Time'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%SZ')
            writer.writerow(data)  # Write data row
    except Exception as e:
        # Log error if CSV saving fails
        logging.error(f"Error saving data to {filename}: {e}")

# ----------------------------------------------Function to fetch data from all NTP servers concurrently--------------------------------
def fetch_data_from_servers(ntp_servers, alert_emails):
    results = []
    # Use thread pool with 4 workers for concurrent queries
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit queries for all servers
        futures = [executor.submit(get_offset_and_delay_from_ntp, server, alert_emails) for server in ntp_servers]
        # Collect results
        for future in futures:
            results.append((None, future.result()))
    
    # Filter valid offsets (non-zero) for average calculation
    valid_offsets = [(offset, data) for _, (offset, _, data) in results if offset != 0]
    if valid_offsets:
        # Calculate average offset across valid servers
        offsets = [offset for offset, _ in valid_offsets]
        avg_offset = sum(offsets) / len(offsets)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # Log and print average offset
        print(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds, Time: {current_time}")
        logging.info(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds")
        
        # Process each server's data
        for _, (offset, delay, data) in results:
            if offset != 0:
                # Calculate deviation from average
                diff = offset - avg_offset
                sign = '+' if diff >= 0 else '-'  # Determine sign of deviation
                data['Offset_Diff_From_Avg'] = diff
                data['Sign'] = sign
                # Log and print deviation
                print(f"Server: {data['Server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                logging.info(f"Server: {data['Server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                
                # Check if deviation exceeds 10 ms (0.01 seconds)
                if abs(diff) > 0.01:
                    # Increment deviation count
                    consecutive_deviations[server] = consecutive_deviations.get(server, 0) + 1
                    # Send alert only after 3 consecutive high deviations
                    if consecutive_deviations[server] >= 3:
                        alert_message = (
                            f"NTP Server Offset Deviation Alert\n"
                            f"Server: {data['Server']}\n"
                            f"Offset: {offset:.6f} seconds\n"
                            f"Delay: {delay:.6f} seconds\n"
                            f"Offset Diff from Avg: {diff:.6f} seconds\n"
                            f"Sign: {sign}\n"
                            f"Time: {current_time}\n"
                            f"Consecutive Deviations: {consecutive_deviations[server]}"
                        )
                        send_alert(alert_message, alert_emails)
                        consecutive_deviations[server] = 0  # Reset after alerting
                else:
                    # Reset deviation count if deviation is within threshold
                    consecutive_deviations[server] = 0
            # Save server data to CSV
            save_to_csv(data)
        
        # Save average data to CSV
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
        # Save data for failed queries
        for _, (_, _, data) in results:
            save_to_csv(data)
        # Log and print if no valid offsets
        print("No valid offsets to calculate average.")
        logging.info("No valid offsets to calculate average.")

# -------------------------------------------------Function to run continuous NTP monitoring---------------------------------------------
def run_ntp_monitoring(ntp_servers, alert_emails):
    try:
        while True:
            # Fetch data from all servers
            fetch_data_from_servers(ntp_servers, alert_emails)
            # Wait 5 minutes before next cycle
            print("Waiting for 5 minutes before collecting data again...")
            time.sleep(300)
            print("Resuming data collection...")
    except KeyboardInterrupt:
        # Handle manual interruption (e.g., Ctrl+C)
        logging.info("Script interrupted. Exiting gracefully...")
    except Exception as e:
        # Log unexpected errors
        logging.error(f"Unexpected error: {e}")

# ---------------------------------------------------------Main execution block------------------------------------------------------
if __name__ == '__main__':
    # List of NTP servers to monitor
    ntp_servers = [
        '157.20.66.8', 'ntp.doca.gov.in', 'samay1.nic.in', 'samay2.nic.in',
        '192.168.251.12', '192.168.251.14', '192.168.251.15', '192.168.251.18',
        '192.168.251.21', '192.168.251.22', '192.168.251.24', '192.168.251.30',
        '192.168.251.32', '192.168.251.33', '192.168.251.38', '192.168.251.39'
    ]
    
    # List of email addresses for alerts
    alert_emails = ['amitnplindia21@gmail.com']
    
    # Initialize failure and deviation counters for each server
    for server in ntp_servers:
        consecutive_failures[server] = 0
        consecutive_deviations[server] = 0
    
    # Start NTP monitoring in a separate thread
    ntp_thread = threading.Thread(target=run_ntp_monitoring, args=(ntp_servers, alert_emails))
    ntp_thread.daemon = True  # Daemon thread exits when main program exits
    ntp_thread.start()
    
    # Run Flask app to handle alert requests
    app.run(debug=True, use_reloader=False)  # Disable reloader to avoid issues with threading