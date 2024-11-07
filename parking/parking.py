import cv2
import pytesseract
import sqlite3
from datetime import datetime
import os
import qrcode
from PIL import Image
import re

# Configure Tesseract path if needed (example for Windows)
pytesseract.pytesseract.tesseract_cmd = r'/opt/homebrew/bin/tesseract'

# Create or connect to SQLite database
conn = sqlite3.connect('parking.db')
cursor = conn.cursor()

# Drop the existing table if it exists and create a new one with the correct schema
cursor.execute('DROP TABLE IF EXISTS parking_records')
cursor.execute('''
CREATE TABLE parking_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number TEXT UNIQUE,
    slot TEXT,
    entry_time TEXT,
    exit_time TEXT,
    fee REAL,
    image BLOB
)
''')
conn.commit()

# Create directories to store captured images and HTML files
image_directory = os.path.abspath('captured_images')
html_directory = os.path.abspath('html_pages')
if not os.path.exists(image_directory):
    os.makedirs(image_directory)
if not os.path.exists(html_directory):
    os.makedirs(html_directory)

# Parking rate per hour
rate_per_hour = 20

# Function to find an available slot
def find_available_slot():
    cursor.execute("SELECT slot FROM parking_records WHERE exit_time IS NULL")
    occupied_slots = {row[0] for row in cursor.fetchall()}
    all_slots = {'A1', 'A2', 'A3', 'A4', 'A5', 'B1', 'B2', 'B3', 'B4', 'B5'}
    available_slots = all_slots - occupied_slots
    return available_slots.pop() if available_slots else None

# Function to capture and recognize number plate using OCR
def capture_plate_number(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Applying Gaussian Blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Use adaptive thresholding for better contrast
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    
    # Applying Morphological transformations to reduce noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    morphed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    # Find contours in the thresholded image
    contours, _ = cv2.findContours(morphed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) == 4:  # Look for quadrilateral shapes (likely a plate)
            x, y, w, h = cv2.boundingRect(approx)
            roi = image[y:y + h, x:x + w]  # Region of Interest

            # Resize the ROI for better OCR accuracy
            roi = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            
            # Experiment with additional thresholding
            _, roi_thresh = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Try to read with Tesseract
            plate_text = pytesseract.image_to_string(roi_thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
            plate_text = re.sub(r'[^A-Z0-9]', '', plate_text)  # Filter non-alphanumeric characters
            if len(plate_text) > 4:  # Check for reasonable plate length
                return plate_text.strip()
    
    return None

# Function to create HTML page with car details
def create_html_page(plate_number, slot, entry_time, exit_time=None, fee=0.0):
    main_menu_path = os.path.abspath('mainmenu.html')
    # Sanitize the plate number to be a valid filename
    sanitized_plate_number = re.sub(r'[<>:"/\\|?*]', "", plate_number)
    html_content = f'''
    <html>
    <head><title>Car Details - {plate_number}</title></head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pes University Navigation</title>
    <img src="../pes1-removebg-preview.png" width="200px" height="200px">
    <h1>Welcome To PES University</h1>
    <style>
    body {{
      font-family: Arial, sans-serif;
      text-align: center;
      background-color: lightblue;
      margin: 0;
      padding: 0;
      height: 100vh;
      border: 2px;
      border-radius: 5%; 
      display: flex;
      justify-content: center;
      align-items: center;
      flex-direction: column;
      color: black;
    }}

    /* Header styling */
    h1 {{
      font-size: 48px;
      margin-bottom: 40px;
      animation: fadeInDown 1.5s ease-out;
      text-shadow: 2px 2px 8px rgba(237, 234, 228, 0.927);
      color: darkblue;
    }}
    a {{
      color: #007BFF;
      text-decoration: none;
      font-weight: bold;
      padding: 5px 10px;
      border-radius: 5px;
      background-color: #E0EFFF;
      transition: color 0.3s, background-color 0.3s;
    }}
    a:hover {{
      color: #0056b3;
      background-color: #CFE2FF;
    }}
    a:active {{
      color: #003A75;
      background-color: #B2D4F5;
    }}
    a:visited {{
      color: #551A8B;
    }}
    </style>
    
    <body>
        <center>
        <h2>Car Details</h2>
        <p><strong>Plate Number:</strong> {plate_number}</p>
        <p><strong>Slot:</strong> {slot}</p>
        <p><strong>Entry Time:</strong> {entry_time}</p>
        <p><strong>Exit Time:</strong> {exit_time if exit_time else "N/A"}</p>
        <p><strong>Fee:</strong> ₹{fee}</p>
        <a href='../mainmenu.html'>Main Menu</a>
        </center>
    </body>
    </html>
    '''
    try:
        # Construct HTML file path using the sanitized plate number
        html_path = os.path.join(html_directory, f"{sanitized_plate_number}.html")
        with open(html_path, 'w', encoding='utf-8') as file:
            file.write(html_content)
        print(f"HTML page created at {html_path}")
        return html_path
    except PermissionError as e:
        print(f"Permission error: {e}")
    except Exception as e:
        print(f"Error creating HTML file: {e}")

# Function to generate QR code that links to the HTML page and display it
def generate_qr_code(html_path, plate_number):
    # Sanitize the plate number to be a valid filename
    sanitized_plate_number = re.sub(r'[<>:"/\\|?*]', "", plate_number)
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f"file://{os.path.abspath(html_path)}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill='black', back_color='white')

    # Save QR code image
    qr_image_path = os.path.join(image_directory, f"{sanitized_plate_number}_qr.png")
    qr_img.save(qr_image_path)

    # Display the QR code in a popup window
    qr_img.show()

# def generate_qr_code(html_filename, plate_number):
#     # Use the Netlify URL instead of the local file path
#     netlify_url = 'https://pesu-nav-parking.netlify.app/'
    
#     # Construct the URL for the HTML page on Netlify
#     url = f"{netlify_url}/{html_filename}"
    
#     qr = qrcode.QRCode(version=1, box_size=10, border=5)
#     qr.add_data(url)
#     qr.make(fit=True)
#     qr_img = qr.make_image(fill='black', back_color='white')

#     # Save QR code image
#     sanitized_plate_number = re.sub(r'[<>:"/\\|?*]', "", plate_number)
#     qr_image_path = os.path.join(image_directory, f"{sanitized_plate_number}_qr.png")
#     qr_img.save(qr_image_path)

#     # Display the QR code in a popup window
#     qr_img.show()

def process_parking(image):
    plate_number = capture_plate_number(image)
    if plate_number:
        # Ask for confirmation of the detected plate number
        print(f"Detected plate number: {plate_number}")
        confirmation = input("Is this plate number correct? (y/n): ").strip().lower()
        
        if confirmation != 'y':
            print("Please rescan the number plate.")
            return  # Exit function to allow for a rescan

        # Check if car is already parked (i.e., entry recorded but no exit time)
        existing_record = cursor.execute('SELECT id, entry_time, slot FROM parking_records WHERE plate_number = ? AND exit_time IS NULL', (plate_number,)).fetchone()
        
        if existing_record:
            # Car is exiting
            entry_time_str = existing_record[1]
            slot = existing_record[2]
            record_id = existing_record[0]
            
            # Calculate parking duration and fee
            entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
            exit_time = datetime.now()
            duration = exit_time - entry_time
            hours = duration.total_seconds() / 3600  # Convert duration to hours
            fee = round(hours * rate_per_hour, 2)
            exit_time_str = exit_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Update the record with exit time and fee
            cursor.execute('''
                UPDATE parking_records 
                SET exit_time = ?, fee = ? 
                WHERE id = ?
            ''', (exit_time_str, fee, record_id))
            conn.commit()
            
            # Update HTML page for the car
            html_path = create_html_page(plate_number, slot, entry_time_str, exit_time_str, fee)
            generate_qr_code(html_path, plate_number)  # Optionally update the QR code
            
            print(f"Car {plate_number} exited from slot {slot}. Total fee: ₹{fee}.")
        
        else:
            # Car is entering
            slot = find_available_slot()
            if slot:
                entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # Convert the image to binary format
                _, buffer = cv2.imencode('.jpg', image)
                binary_image = buffer.tobytes()
                
                # Insert new parking record
                cursor.execute('''
                    INSERT INTO parking_records (plate_number, slot, entry_time, image) 
                    VALUES (?, ?, ?, ?)
                ''', (plate_number, slot, entry_time, binary_image))
                conn.commit()
                
                print(f"Car {plate_number} is assigned to slot {slot} at {entry_time}.")
                
                # Create an HTML page and generate a QR code
                html_path = create_html_page(plate_number, slot, entry_time)
                generate_qr_code(html_path, plate_number)
                print(f"QR code generated for car {plate_number}. Check {os.path.abspath(html_path)} for details.")
            else:
                print("No available parking slots.")
    else:
        print("Plate number not detected. Please try again.")



# Function to continuously open the camera until 'q' is pressed
def capture_from_camera():
    cap = cv2.VideoCapture(0)
    print("Press 's' to scan the plate or 'q' to quit.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture image from camera.")
            break
            
        cv2.imshow("Camera", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord("s"):
            process_parking(frame)
        elif key == ord("q"):
            print("Quitting camera mode.")
            break

    cap.release()
    cv2.destroyAllWindows()

# Start the program by directly opening the camera
try:
    capture_from_camera()
finally:
    conn.close()
