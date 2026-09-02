from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fruver.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

UNIDADES_VALIDAS = {'kg', 'libra', 'unidad', 'atado'}
CATEGORIAS_VALIDAS = {'fruta', 'verdura', 'tuberculo', 'hierba', 'otro'}
STOCK_BAJO_UMBRAL = 5


# ---------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------
class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False, unique=True)
    precio = db.Column(db.Float, nullable=False, default=0)
    unidad = db.Column(db.String(20), nullable=False, default='unidad')
    categoria = db.Column(db.String(20), nullable=False, default='otro')
    cantidad_disponible = db.Column(db.Float, nullable=False, default=0)

    historial = db.relationship(
        'HistorialPrecio', backref='producto', cascade='all, delete-orphan'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'precio': self.precio,
            'unidad': self.unidad,
            'categoria': self.categoria,
            'cantidad_disponible': self.cantidad_disponible,
            'stock_bajo': self.cantidad_disponible <= STOCK_BAJO_UMBRAL,
        }


class HistorialPrecio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    precio_anterior = db.Column(db.Float, nullable=False)
    precio_nuevo = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'precio_anterior': self.precio_anterior,
            'precio_nuevo': self.precio_nuevo,
            'fecha': self.fecha.isoformat(),
        }


# ---------------------------------------------------------------
# Validación
# ---------------------------------------------------------------
def validar_producto(datos, es_creacion=False):
    """Devuelve un mensaje de error, o None si los datos son válidos."""
    if es_creacion and not datos.get('nombre', '').strip():
        return 'El nombre es obligatorio.'

    if 'precio' in datos:
        try:
            if float(datos['precio']) < 0:
                return 'El precio no puede ser negativo.'
        except (TypeError, ValueError):
            return 'El precio debe ser un número.'

    if 'cantidad_disponible' in datos:
        try:
            if float(datos['cantidad_disponible']) < 0:
                return 'La cantidad disponible no puede ser negativa.'
        except (TypeError, ValueError):
            return 'La cantidad disponible debe ser un número.'

    if 'unidad' in datos and datos['unidad'] not in UNIDADES_VALIDAS:
        return f"Unidad inválida. Usa una de: {', '.join(sorted(UNIDADES_VALIDAS))}."

    if 'categoria' in datos and datos['categoria'] not in CATEGORIAS_VALIDAS:
        return f"Categoría inválida. Usa una de: {', '.join(sorted(CATEGORIAS_VALIDAS))}."

    return None


# ---------------------------------------------------------------
# Manejo de errores centralizado
# ---------------------------------------------------------------
@app.errorhandler(404)
def no_encontrado(e):
    return jsonify({'error': 'Recurso no encontrado'}), 404


@app.errorhandler(500)
def error_interno(e):
    return jsonify({'error': 'Error interno del servidor'}), 500


# ---------------------------------------------------------------
# Vista principal
# ---------------------------------------------------------------
@app.route('/')
def inicio():
    return render_template('fruver.html')


# ---------------------------------------------------------------
# GET: listar productos (con filtros opcionales)
# /api/productos?categoria=fruta&nombre=man
# ---------------------------------------------------------------
@app.route('/api/productos', methods=['GET'])
def obtener_productos():
    query = Producto.query

    categoria = request.args.get('categoria')
    if categoria:
        query = query.filter(Producto.categoria == categoria)

    nombre = request.args.get('nombre')
    if nombre:
        query = query.filter(Producto.nombre.ilike(f'%{nombre}%'))

    productos = query.order_by(Producto.nombre).all()
    return jsonify([p.to_dict() for p in productos]), 200


# GET: un producto por ID
@app.route('/api/productos/<int:id>', methods=['GET'])
def obtener_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404
    return jsonify(producto.to_dict()), 200


# GET: historial de precios de un producto
@app.route('/api/productos/<int:id>/historial', methods=['GET'])
def obtener_historial(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404
    historial = sorted(producto.historial, key=lambda h: h.fecha, reverse=True)
    return jsonify([h.to_dict() for h in historial]), 200


# POST: crear un nuevo producto
@app.route('/api/productos', methods=['POST'])
def crear_producto():
    # 1. La solicitud debe venir en formato JSON
    if not request.is_json:
        return jsonify({'error': 'Solicitud debe ser JSON'}), 400

    datos = request.get_json()

    # 2. nombre y precio son obligatorios
    if not datos.get('nombre') or datos.get('precio') is None:
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    # 3. Validaciones adicionales del proyecto (tipos, unidad, categoría)
    error = validar_producto(datos, es_creacion=True)
    if error:
        return jsonify({'error': error}), 400

    if Producto.query.filter_by(nombre=datos['nombre'].strip()).first():
        return jsonify({'error': 'Ya existe un producto con ese nombre'}), 409

    producto = Producto(
        nombre=datos['nombre'].strip(),
        precio=float(datos.get('precio', 0)),
        unidad=datos.get('unidad', 'unidad'),
        categoria=datos.get('categoria', 'otro'),
        cantidad_disponible=float(datos.get('cantidad_disponible', 0)),
    )
    db.session.add(producto)
    db.session.commit()

    return jsonify(producto.to_dict()), 201

# PUT: actualizar un producto completo
@app.route('/api/productos/<int:id>', methods=['PUT'])
def actualizar_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404

    if not request.is_json:
        return jsonify({'error': 'Solicitud debe ser JSON'}), 400

    datos = request.get_json()

    if not datos.get('nombre') or datos.get('precio') is None:
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    error = validar_producto(datos)
    if error:
        return jsonify({'error': error}), 400

    # Validar que el nuevo nombre no esté ocupado por OTRO producto distinto al actual
    nuevo_nombre = datos['nombre'].strip()
    existente = Producto.query.filter_by(nombre=nuevo_nombre).first()
    if existente and existente.id != producto.id:
        return jsonify({'error': 'Ya existe otro producto con ese nombre'}), 409

    _aplicar_cambios(producto, datos)
    db.session.commit()
    return jsonify(producto.to_dict()), 200


# PATCH: modificar parcialmente un producto
@app.route('/api/productos/<int:id>', methods=['PATCH'])
def modificar_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404

    datos = request.get_json() or {}
    error = validar_producto(datos)
    if error:
        return jsonify({'error': error}), 400

    _aplicar_cambios(producto, datos)
    db.session.commit()
    return jsonify(producto.to_dict()), 200


def _aplicar_cambios(producto, datos):
    """Aplica los campos recibidos y registra el precio en el historial si cambió."""
    if 'precio' in datos:
        precio_nuevo = float(datos['precio'])
        if precio_nuevo != producto.precio:
            db.session.add(HistorialPrecio(
                producto_id=producto.id,
                precio_anterior=producto.precio,
                precio_nuevo=precio_nuevo,
            ))
        producto.precio = precio_nuevo

    for campo in ('nombre', 'unidad', 'categoria', 'cantidad_disponible'):
        if campo in datos:
            valor = datos[campo]
            setattr(producto, campo, float(valor) if campo == 'cantidad_disponible' else valor)


# POST: registrar una venta (descuenta stock)
@app.route('/api/productos/<int:id>/vender', methods=['POST'])
def vender_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404

    datos = request.get_json() or {}
    try:
        cantidad = float(datos.get('cantidad', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'La cantidad debe ser un número'}), 400

    if cantidad <= 0:
        return jsonify({'error': 'La cantidad debe ser mayor a cero'}), 400
    if cantidad > producto.cantidad_disponible:
        return jsonify({'error': 'No hay suficiente stock disponible'}), 400

    producto.cantidad_disponible -= cantidad
    db.session.commit()

    return jsonify({
        'producto': producto.to_dict(),
        'vendido': cantidad,
        'total': round(cantidad * producto.precio, 2),
    }), 200


# DELETE: eliminar un producto
@app.route('/api/productos/<int:id>', methods=['DELETE'])
def eliminar_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        return jsonify({'error': 'Producto no encontrado'}), 404

    db.session.delete(producto)
    db.session.commit()
    return jsonify({'mensaje': 'Producto eliminado'}), 200


# ---------------------------------------------------------------
# Inicialización de la base de datos con datos de ejemplo
# ---------------------------------------------------------------
def inicializar_datos():
    db.create_all()
    if Producto.query.first():
        return  # ya hay datos, no volver a sembrar

    ejemplos = [
        Producto(nombre='Tomate chonto', precio=3500, unidad='kg', categoria='verdura', cantidad_disponible=40),
        Producto(nombre='Aguacate hass', precio=6000, unidad='unidad', categoria='fruta', cantidad_disponible=25),
        Producto(nombre='Plátano verde', precio=2200, unidad='kg', categoria='fruta', cantidad_disponible=60),
        Producto(nombre='Cilantro', precio=1000, unidad='atado', categoria='hierba', cantidad_disponible=15),
        Producto(nombre='Papa criolla', precio=4200, unidad='libra', categoria='tuberculo', cantidad_disponible=3),
    ]
    db.session.add_all(ejemplos)
    db.session.commit()


with app.app_context():
    inicializar_datos()


if __name__ == '__main__':
    app.run(debug=True, port=5000)