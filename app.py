from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import os
from werkzeug.utils import secure_filename
from sqlalchemy import func

app = Flask(__name__)
app.secret_key = 'supersecretkey123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
db = SQLAlchemy(app)

ADMIN_PASSWORD = 'admin123'

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(100), nullable=False)
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


def init_db():
    with app.app_context():
        db.create_all()
        if not Product.query.first():
            products = [
                Product(name="Classic Tee", price=19.99, image="images/tee.jpg",
                        description="Comfortable cotton t-shirt"),
                Product(name="Denim Jeans", price=49.99, image="images/jeans.jpg", description="Stylish blue jeans"),
                Product(name="Leather Jacket", price=89.99, image="images/jacket.jpg",
                        description="Premium leather jacket"),
                Product(name="Sneakers", price=59.99, image="images/sneakers.jpg", description="Trendy casual shoes")
            ]
            db.session.bulk_save_objects(products)
            db.session.commit()


@app.route('/', methods=['GET'])
def index():
    search_query = request.args.get('search', '')
    if search_query:
        products = Product.query.filter(Product.name.ilike(f'%{search_query}%') |
                                        Product.description.ilike(f'%{search_query}%')).all()
        message = "No products found matching your search." if not products else None
    else:
        products = Product.query.all()
        message = None
    return render_template('index.html', products=products, message=message, search_query=search_query)


@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search', '')
    return redirect(url_for('index', search=search_query))


@app.route('/cart', methods=['GET', 'POST'])
def cart():
    if request.method == 'POST':
        data = request.get_json()
        product_id = data.get('product_id')
        quantity = data.get('quantity', 1)

        if not product_id:
            return jsonify({'message': 'Product ID required'}), 400

        existing_item = CartItem.query.filter_by(product_id=product_id).first()
        if existing_item:
            existing_item.quantity += int(quantity)
        else:
            cart_item = CartItem(product_id=product_id, quantity=int(quantity))
            db.session.add(cart_item)
        db.session.commit()
        return jsonify({'message': 'Added to cart', 'cart_count': CartItem.query.count()})
    return render_template('cart.html')


@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    data = request.get_json()
    quantity_to_remove = int(data.get('quantity', 1))
    item = CartItem.query.filter_by(product_id=product_id).first()
    if item:
        if item.quantity <= quantity_to_remove:
            db.session.delete(item)
        else:
            item.quantity -= quantity_to_remove
        db.session.commit()
        return jsonify({'message': f'Removed {quantity_to_remove} item(s)', 'cart_count': CartItem.query.count()})
    return jsonify({'message': 'Item not found'}), 404


@app.route('/cart/data')
def cart_data():
    cart_items = db.session.query(CartItem.product_id, func.sum(CartItem.quantity).label('total_quantity')) \
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
    return jsonify({'items': cart, 'total': total})


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        data = request.form
        items = CartItem.query.all()

        if not items:
            return render_template('checkout.html', error="Cart is empty")

        for item in items:
            order = Order(
                product_id=item.product_id,
                quantity=item.quantity,
                customer_name=data['name'],
                customer_phone=data['phone'],
                status='Pending'
            )
            db.session.add(order)
            db.session.delete(item)
        db.session.commit()
        session['buyer_phone'] = data['phone']
        return render_template('checkout.html', success="Order placed successfully!")
    return render_template('checkout.html')


@app.route('/orders', methods=['GET', 'POST'])
def orders():
    role = request.args.get('role', 'buyer')

    if role == 'buyer' and request.method == 'POST' and 'buyer_phone' in request.form:
        phone = request.form['buyer_phone']
        if Order.query.filter_by(customer_phone=phone).first():
            session['buyer_phone'] = phone
        else:
            return render_template('orders.html', role=role, error="No orders found for this phone number")

    if role == 'seller' and request.method == 'POST' and 'password' in request.form:
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
        else:
            return render_template('orders.html', role=role, error="Incorrect password")

    if role == 'buyer' and not session.get('buyer_phone'):
        return render_template('orders.html', role=role)
    if role == 'seller' and not session.get('admin_logged_in'):
        return render_template('orders.html', role=role)

    if role == 'buyer':
        buyer_phone = session.get('buyer_phone')
        orders = db.session.query(Order.product_id, func.sum(Order.quantity).label('total_quantity'), Order.status) \
            .filter_by(customer_phone=buyer_phone) \
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
                                  Order.customer_name, Order.customer_phone, Order.status) \
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
                new_product = Product(name=name, price=price, image=image_path, description=description)
                db.session.add(new_product)
                db.session.commit()
                return redirect(url_for('orders', role='seller'))
            else:
                return render_template('orders.html', role=role, dashboard_data=dashboard_data,
                                       products=products, admin_logged_in=True, error="Invalid image file")

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
                        product.image = f"images/{filename}"
                db.session.commit()
            return redirect(url_for('orders', role='seller'))

        if request.method == 'POST' and 'update_status' in request.form:
            product_id = int(request.form['product_id'])
            customer_phone = request.form['customer_phone']
            new_status = request.form['status']
            orders_to_update = Order.query.filter_by(product_id=product_id, customer_phone=customer_phone).all()
            for order in orders_to_update:
                order.status = new_status
            db.session.commit()
            return redirect(url_for('orders', role='seller'))

    else:
        return redirect(url_for('orders'))

    return render_template('orders.html', orders=order_list, role=role, dashboard_data=dashboard_data,
                           admin_logged_in=session.get('admin_logged_in'),
                           products=products if role == 'seller' else None,
                           buyer_phone=session.get('buyer_phone') if role == 'buyer' else None)


@app.route('/orders/delete/<int:product_id>/<customer_phone>', methods=['POST'])
def delete_order(product_id, customer_phone):
    if not session.get('admin_logged_in'):
        return jsonify({'message': 'Unauthorized'}), 403

    orders_to_delete = Order.query.filter_by(product_id=product_id, customer_phone=customer_phone).all()
    if orders_to_delete:
        for order in orders_to_delete:
            db.session.delete(order)
        db.session.commit()
        return jsonify({'message': 'Order deleted successfully'}), 200
    return jsonify({'message': 'Order not found'}), 404


@app.route('/logout', methods=['POST'])
def logout():
    if session.get('admin_logged_in'):
        session.pop('admin_logged_in', None)
    elif session.get('buyer_phone'):
        session.pop('buyer_phone', None)
    role = request.args.get('role', 'buyer')
    return redirect(url_for('orders', role=role))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)