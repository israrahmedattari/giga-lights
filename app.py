import os
import sqlite3
import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import json, os
from functools import wraps

app = Flask(__name__)
app.secret_key = "giga_lights_super_secret_key"

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            wattage TEXT,
            lumens TEXT,
            image_url TEXT NOT NULL,
            description TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            customer_address TEXT NOT NULL,
            items_json TEXT NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper function to convert DB rows to clean Python dicts
def fetch_all_as_dicts(query, params=()):
    conn = get_db_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ==================== CUSTOMER ROUTES ====================
@app.route('/')
def index():
    category_filter = request.args.get('category')
    
    if category_filter:
        products = fetch_all_as_dicts('SELECT * FROM products WHERE category = ?', (category_filter,))
    else:
        products = fetch_all_as_dicts('SELECT * FROM products')
        
    return render_template('index.html', products=products, current_category=category_filter)

@app.route('/cart')
def cart():
    return render_template('cart.html')

@app.route('/place_order', methods=['POST'])
def place_order():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    address = data.get('address')
    cart_items = data.get('cart')
    total = data.get('total')

    if not cart_items or not name or not phone:
        return jsonify({'success': False, 'message': 'Missing order details'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    for item in cart_items:
        prod = cursor.execute('SELECT quantity FROM products WHERE id = ?', (item['id'],)).fetchone()
        if prod and prod['quantity'] >= item['qty']:
            new_qty = prod['quantity'] - item['qty']
            cursor.execute('UPDATE products SET quantity = ? WHERE id = ?', (new_qty, item['id']))
        else:
            conn.close()
            return jsonify({'success': False, 'message': f"Insufficient stock for product ID {item['id']}"}), 400

    cursor.execute('''
        INSERT INTO orders (customer_name, customer_phone, customer_address, items_json, total_amount)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, phone, address, json.dumps(cart_items), total))

    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Initialize summary before appending values
    summary = f"📦 *Order #{order_id} Summary:*\n"
    for item in cart_items:
        summary += f"- {item['title']} x {item['qty']} = PKR {item['price'] * item['qty']:.2f}\n"
    summary += f"\n💰 *Total:* PKR {total:.2f}"

    return jsonify({
        'success': True,
        'order_id': order_id,
        'message_summary': summary
    })

# ==================== ADMIN ROUTES ====================

# Set your secret password here
ADMIN_PASSWORD = "admin123"

# Helper Decorator to lock routes
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== ADMIN ROUTES ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash("Welcome back, Admin!", "success")
            return redirect(url_for('admin'))
        else:
            flash("Invalid password!", "danger")
    
    return '''
        <div style="background:#080B10; color:#fff; min-height:100vh; display:flex; justify-content:center; align-items:center; font-family:sans-serif;">
            <form method="POST" style="background:#111622; padding:40px; border-radius:16px; border:1px solid #00f2fe; text-align:center; box-shadow:0 0 20px rgba(0,242,254,0.2);">
                <h2 style="color:#00f2fe; margin-bottom:20px;">🔒 GIGA LIGHTS Admin</h2>
                <input type="password" name="password" placeholder="Enter Admin Password" style="padding:12px; border-radius:8px; border:1px solid #333; margin-bottom:20px; width:220px; outline:none;" required><br>
                <button type="submit" style="background:#00f2fe; color:#000; border:none; padding:12px 24px; font-weight:bold; border-radius:8px; cursor:pointer;">Login</button>
            </form>
        </div>
    '''

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash("Logged out successfully.", "info")
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin():
    products = fetch_all_as_dicts('SELECT * FROM products ORDER BY id DESC')
    orders_raw = fetch_all_as_dicts('SELECT * FROM orders ORDER BY id DESC')
    
    parsed_orders = []
    for order in orders_raw:
        order['items'] = json.loads(order['items_json'])
        parsed_orders.append(order)

    return render_template('admin.html', products=products, orders=parsed_orders)

@app.route('/admin/add_product', methods=['POST'])
@admin_required
def add_product():
    title = request.form['title']
    category = request.form['category']
    price = float(request.form['price'])
    quantity = int(request.form['quantity'])
    wattage = request.form['wattage']
    lumens = request.form['lumens']
    description = request.form['description']

    file = request.files.get('image_file')
    image_url = request.form.get('image_url')

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        final_image_path = f"/static/uploads/{filename}"
    elif image_url:
        final_image_path = image_url
    else:
        final_image_path = "https://images.unsplash.com/photo-1550985616-10810253b84d?w=600"

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO products (title, category, price, quantity, wattage, lumens, image_url, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (title, category, price, quantity, wattage, lumens, final_image_path, description))
    conn.commit()
    conn.close()

    flash("Product added successfully!", "success")
    return redirect(url_for('admin'))

@app.route('/admin/delete_product/<int:id>')
@admin_required
def delete_product(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM products WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash("Product deleted!", "danger")
    return redirect(url_for('admin'))

@app.route('/admin/update_order_status/<int:order_id>', methods=['POST'])
@admin_required
def update_order_status(order_id):
    new_status = request.form.get('status')
    
    conn = get_db_connection()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    
    flash(f"Order #{order_id} status updated to {new_status}!", "success")
    return redirect(url_for('admin'))
    
@app.route('/warranty')
def warranty():
    return render_template('warranty.html')

@app.route('/shipping')
def shipping():
    return render_template('shipping.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)