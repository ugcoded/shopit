from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FileField
from wtforms.validators import DataRequired, Length
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_caching import Cache
import os
from werkzeug.utils import secure_filename
from sqlalchemy import func
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///shop.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['CACHE_TYPE'] = 'SimpleCache'
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
cache = Cache(app)

if not app.secret_key:
    raise ValueError("SECRET_KEY must be set in environment variables")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    images = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(200))

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    product = db.relationship('Product')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    product = db.relationship('Product')

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Branding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    logo_path = db.Column(db.String(100))
    site_name = db.Column(db.String(100), default='Elite Shop')

class AdminForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6, max=100)])
    submit = SubmitField('Add Admin')

class BrandingForm(FlaskForm):
    site_name = StringField('Site Name', validators=[DataRequired(), Length(max=100)])
    logo = FileField('Site Logo')
    submit = SubmitField('Update Branding')

class AdminLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=50)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6, max=100)])
    submit = SubmitField('Login')

class CheckoutForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(min=10, max=20)])
    submit = SubmitField('Place Order')

def init_db():
    try:
        with app.app_context():
            logger.info("Initializing database...")
            db.drop_all()
            db.create_all()
            if not Product.query.first():
                products = [
                    Product(name="Classic Tee", price=19.99, images="images/tee1.jpg,images/tee2.jpg", description="Comfortable cotton t-shirt"),
                    Product(name="Denim Jeans", price=49.99, images="images/jeans1.jpg,images/jeans2.jpg", description="Stylish blue jeans"),
                    Product(name="Leather Jacket", price=89.99, images="images/jacket1.jpg,images/jacket2.jpg", description="Premium leather jacket"),
                    Product(name="Sneakers", price=59.99, images="images/sneakers1.jpg,images/sneakers2.jpg", description="Trendy casual shoes")
                ]
                db.session.bulk_save_objects(products)
                logger.info("Added default products with multiple images")
            if not Admin.query.first():
                admin = Admin(username='admin', password='admin123')
                db.session.add(admin)
                logger.info("Added default admin: admin/admin123")
            if not Branding.query.first():
                branding = Branding(site_name='Elite Shop')
                db.session.add(branding)
                logger.info("Added default branding")
            db.session.commit()
            logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise

init_db()

@app.before_request
def enforce_https():
    if request.url.startswith('http://') and os.environ.get('FLASK_ENV') == 'production':
        return redirect(request.url.replace('http://', 'https://'), code=301)

@app.route('/', methods=['GET'])
@cache.cached(timeout=60)
def index():
    search_query = request.args.get('search', '')
    branding = Branding.query.first()
    if search_query:
        products = Product.query.filter(Product.name.ilike(f'%{search_query}%')).all()
        message = "No products found matching your search." if not products else None
    else:
        products = Product.query.all()
        message = None
    cart_count = CartItem.query.count()
    return render_template('index.html', products=products, message=message, search_query=search_query, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search', '')
    return redirect(url_for('index', search=search_query))

@app.route('/cart', methods=['GET', 'POST'])
@csrf.exempt
def cart():
    branding = Branding.query.first()
    cart_count = CartItem.query.count()
    if request.method == 'POST':
        data = request.get_json()
        logger.info(f"Received cart data: {data}")
        product_id = data.get('product_id')
        quantity = data.get('quantity', 1)
        
        if not product_id:
            logger.error("Product ID missing in request")
            return jsonify({'message': 'Product ID required'}), 400
        
        try:
            quantity = int(quantity)
            if quantity < 1:
                raise ValueError("Quantity must be positive")
            existing_item = CartItem.query.filter_by(product_id=product_id).first()
            if existing_item:
                existing_item.quantity += quantity
            else:
                cart_item = CartItem(product_id=product_id, quantity=quantity)
                db.session.add(cart_item)
            db.session.commit()
            updated_count = CartItem.query.count()
            logger.info(f"Added product {product_id} to cart with quantity {quantity}")
            flash('Item added to cart!', 'success')
            return jsonify({'message': 'Added to cart', 'cart_count': updated_count})
        except ValueError as e:
            logger.error(f"Invalid quantity: {str(e)}")
            return jsonify({'message': f'Invalid quantity: {str(e)}'}), 400
        except Exception as e:
            logger.error(f"Error adding to cart: {str(e)}")
            db.session.rollback()
            return jsonify({'message': 'Error adding to cart'}), 500
    return render_template('cart.html', branding=branding, cart_count=cart_count, csrf_token=generate_csrf())

@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    data = request.get_json()
    if not data or 'quantity' not in data:
        return jsonify({'message': 'Invalid request data'}), 400
    
    quantity_to_remove = int(data.get('quantity', 1))
    try:
        item = CartItem.query.filter_by(product_id=product_id).first()
        if item:
            if item.quantity <= quantity_to_remove:
                db.session.delete(item)
            else:
                item.quantity -= quantity_to_remove
            db.session.commit()
            updated_count = CartItem.query.count()
            flash(f'Removed {quantity_to_remove} item(s) from cart!', 'success')
            return jsonify({'message': f'Removed {quantity_to_remove} item(s)', 'cart_count': updated_count})
        return jsonify({'message': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error removing item from cart: {str(e)}")
        db.session.rollback()
        return jsonify({'message': 'Error removing item from cart'}), 500

@app.route('/cart/data')
def cart_data():
    cart_items = db.session.query(CartItem.product_id, func.sum(CartItem.quantity).label('total_quantity'))\
                           .group_by(CartItem.product_id).all()
    cart = []
    total = 0
    for product_id, quantity in cart_items:
        product = Product.query.get(product_id)
        cart.append({
            'id': product_id,
            'name': product.name,
            'price': product.price,
            'quantity': quantity
        })
        total += product.price * quantity
    return jsonify({'items': cart, 'total': total, 'cart_count': CartItem.query.count()})

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    branding = Branding.query.first()
    form = CheckoutForm()
    cart_count = CartItem.query.count()
    if request.method == 'POST' and form.validate_on_submit():
        items = CartItem.query.all()
        if not items:
            flash('Cart is empty!', 'error')
            return render_template('checkout.html', form=form, error="Cart is empty", branding=branding, cart_count=cart_count)
        
        for item in items:
            order = Order(
                product_id=item.product_id,
                quantity=item.quantity,
                customer_name=form.name.data,
                customer_phone=form.phone.data,
                status='Pending'
            )
            db.session.add(order)
            db.session.delete(item)
        db.session.commit()
        session['buyer_phone'] = form.phone.data
        flash(f'Order placed successfully! Use your phone number ({form.phone.data}) to track your order.', 'success')
        return redirect(url_for('orders', role='buyer'))
    return render_template('checkout.html', form=form, branding=branding, cart_count=cart_count)

@app.route('/orders', methods=['GET', 'POST'])
def orders():
    branding = Branding.query.first()
    role = request.args.get('role', 'buyer')
    admin_login_form = AdminLoginForm()
    cart_count = CartItem.query.count()
    
    if role == 'buyer' and request.method == 'POST' and 'buyer_phone' in request.form:
        phone = request.form['buyer_phone']
        if Order.query.filter_by(customer_phone=phone).first():
            session['buyer_phone'] = phone
            flash('Logged in successfully!', 'success')
        else:
            flash('No orders found for this phone number.', 'error')
            return render_template('orders.html', role=role, error="No orders found for this phone number", branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
    
    if role == 'seller' and request.method == 'POST' and admin_login_form.validate_on_submit():
        username = admin_login_form.username.data
        password = admin_login_form.password.data
        logger.info(f"Attempting login with username: {username}, password: {password}")
        admin = Admin.query.filter_by(username=username).first()
        if admin:
            logger.info(f"Found admin: {admin.username}, stored password: {admin.password}")
            if admin.password == password:
                session['admin_logged_in'] = True
                session['admin_username'] = username
                flash('Admin logged in successfully!', 'success')
            else:
                flash('Incorrect password.', 'error')
                return render_template('orders.html', role=role, error="Incorrect password", admin_login_form=admin_login_form, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
        else:
            flash('Username not found.', 'error')
            return render_template('orders.html', role=role, error="Username not found", admin_login_form=admin_login_form, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
    
    if role == 'buyer' and not session.get('buyer_phone'):
        return render_template('orders.html', role=role, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
    if role == 'seller' and not session.get('admin_logged_in'):
        return render_template('orders.html', role=role, admin_login_form=admin_login_form, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
    
    if role == 'buyer':
        buyer_phone = session.get('buyer_phone')
        orders = db.session.query(Order.product_id, func.sum(Order.quantity).label('total_quantity'), Order.status)\
                           .filter_by(customer_phone=buyer_phone)\
                           .group_by(Order.product_id, Order.status).all()
        order_list = []
        total_spent = 0
        for product_id, quantity, status in orders:
            product = Product.query.get(product_id)
            order_list.append({
                'product_id': product_id,
                'name': product.name,
                'quantity': quantity,
                'total_price': product.price * quantity,
                'status': status
            })
            total_spent += product.price * quantity
        dashboard_data = {
            'total_orders': len(orders),
            'total_spent': total_spent
        }
    elif role == 'seller' and session.get('admin_logged_in'):
        orders = db.session.query(Order.product_id, func.sum(Order.quantity).label('total_quantity'), 
                                 Order.customer_name, Order.customer_phone, Order.status)\
                           .group_by(Order.product_id, Order.customer_name, Order.customer_phone, Order.status).all()
        order_list = []
        total_revenue = 0
        for product_id, quantity, customer_name, customer_phone, status in orders:
            product = Product.query.get(product_id)
            order_list.append({
                'product_id': product_id,
                'name': product.name,
                'quantity': quantity,
                'total_price': product.price * quantity,
                'customer_name': customer_name,
                'customer_phone': customer_phone,
                'status': status
            })
            total_revenue += product.price * quantity
        products = Product.query.all()
        dashboard_data = {
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'products_count': len(products)
        }
        
        if request.method == 'POST' and 'product_name' in request.form:
            name = request.form['product_name']
            price = float(request.form['product_price'])
            description = request.form['product_description']
            file = request.files['product_image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_path = f"images/{filename}"
                new_product = Product(name=name, price=price, images=image_path, description=description)
                db.session.add(new_product)
                db.session.commit()
                flash('Product added successfully!', 'success')
                return redirect(url_for('orders', role='seller'))
            else:
                flash('Invalid image file.', 'error')
                return render_template('orders.html', role=role, dashboard_data=dashboard_data, 
                                     products=products, admin_logged_in=True, error="Invalid image file", branding=branding, cart_count=cart_count, csrf_token=generate_csrf())
        
        if request.method == 'POST' and 'edit_product_id' in request.form:
            product_id = request.form['edit_product_id']
            product = Product.query.get(product_id)
            if product:
                product.name = request.form['edit_product_name']
                product.price = float(request.form['edit_product_price'])
                product.description = request.form['edit_product_description']
                if 'edit_product_image' in request.files and request.files['edit_product_image'].filename:
                    file = request.files['edit_product_image']
                    if file and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        product.images = f"{product.images},{filename}" if product.images else filename
                db.session.commit()
                flash('Product updated successfully!', 'success')
            return redirect(url_for('orders', role='seller'))
        
        if request.method == 'POST' and 'update_status' in request.form:
            product_id = int(request.form['product_id'])
            customer_phone = request.form['customer_phone']
            new_status = request.form['status']
            orders_to_update = Order.query.filter_by(product_id=product_id, customer_phone=customer_phone).all()
            for order in orders_to_update:
                order.status = new_status
            db.session.commit()
            flash('Order status updated!', 'success')
            return redirect(url_for('orders', role='seller'))
    
    else:
        return redirect(url_for('orders'))
    
    return render_template('orders.html', orders=order_list, role=role, dashboard_data=dashboard_data, 
                         admin_logged_in=session.get('admin_logged_in'), products=products if role == 'seller' else None,
                         buyer_phone=session.get('buyer_phone') if role == 'buyer' else None, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())

@app.route('/orders/delete/<int:product_id>/<customer_phone>', methods=['POST'])
def delete_order(product_id, customer_phone):
    if not session.get('admin_logged_in'):
        return jsonify({'message': 'Unauthorized'}), 403
    
    orders_to_delete = Order.query.filter_by(product_id=product_id, customer_phone=customer_phone).all()
    if orders_to_delete:
        for order in orders_to_delete:
            db.session.delete(order)
        db.session.commit()
        flash('Order deleted successfully!', 'success')
        return jsonify({'message': 'Order deleted successfully'}), 200
    flash('Order not found.', 'error')
    return jsonify({'message': 'Order not found'}), 404

@app.route('/manage_admins', methods=['GET', 'POST'])
def manage_admins():
    if not session.get('admin_logged_in'):
        flash('You must be logged in as an admin.', 'error')
        return redirect(url_for('orders', role='seller'))
    
    branding = Branding.query.first()
    form = AdminForm()
    cart_count = CartItem.query.count()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        if Admin.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
        else:
            new_admin = Admin(username=username, password=password)
            db.session.add(new_admin)
            db.session.commit()
            flash(f'Admin {username} added successfully!', 'success')
    
    admins = Admin.query.all()
    if request.method == 'POST' and 'change_password' in request.form:
        admin_id = int(request.form['admin_id'])
        new_password = request.form['new_password']
        admin = Admin.query.get(admin_id)
        if admin:
            admin.password = new_password
            db.session.commit()
            flash(f'Password for {admin.username} updated successfully!', 'success')
    
    return render_template('manage_admins.html', form=form, admins=admins, branding=branding, cart_count=cart_count, csrf_token=generate_csrf())

@app.route('/branding', methods=['GET', 'POST'])
def branding():
    if not session.get('admin_logged_in'):
        flash('You must be logged in as an admin.', 'error')
        return redirect(url_for('orders', role='seller'))
    
    branding = Branding.query.first()
    form = BrandingForm(obj=branding)
    cart_count = CartItem.query.count()
    if form.validate_on_submit():
        branding.site_name = form.site_name.data
        if form.logo.data and allowed_file(form.logo.data.filename):
            filename = secure_filename(form.logo.data.filename)
            form.logo.data.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            branding.logo_path = f"images/{filename}"
        db.session.commit()
        flash('Branding updated successfully!', 'success')
        return redirect(url_for('orders', role='seller'))
    
    return render_template('branding.html', form=form, branding=branding, cart_count=cart_count)

@app.route('/logout', methods=['POST'])
def logout():
    logger.info(f"Logout requested. Current session: {session}")
    if session.get('admin_logged_in'):
        session.pop('admin_logged_in', None)
        session.pop('admin_username', None)
        flash('Logged out successfully!', 'success')
        logger.info("Admin logged out successfully")
    elif session.get('buyer_phone'):
        session.pop('buyer_phone', None)
        flash('Logged out successfully!', 'success')
        logger.info("Buyer logged out successfully")
    role = request.args.get('role', 'buyer')
    logger.info(f"Redirecting to orders page with role: {role}")
    return redirect(url_for('orders', role=role))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
