from extensions import db

class Device(db.Model):
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    
    platforms = db.relationship('Platform', backref='device', lazy='dynamic', cascade='all, delete-orphan')
