import os
from flask import Flask
from config import Config
from extensions import db, login_manager
from models import User

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Ensure upload directory exists
    os.makedirs(app.config['ROM_UPLOAD_PATH'], exist_ok=True)
    os.makedirs(os.path.join(app.config['ROM_UPLOAD_PATH'], 'bios'), exist_ok=True)

    # Register blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.devices import devices_bp
    from routes.platforms import platforms_bp
    from routes.roms import roms_bp
    from routes.saves import saves_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(devices_bp, url_prefix='/devices')
    app.register_blueprint(platforms_bp, url_prefix='/platforms')
    app.register_blueprint(roms_bp, url_prefix='/roms')
    app.register_blueprint(saves_bp, url_prefix='/saves')

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Auto-initialize database
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("Database schema verified and loaded.")

            # Check if admin user exists, if not, create
            if not User.query.first():
                admin = User(username='admin')
                admin.set_password('admin')
                db.session.add(admin)
                db.session.commit()
                app.logger.info("Initialized database with default admin user.")
            else:
                app.logger.info("Database connection and admin user verification successful.")
        except Exception as e:
            app.logger.error(f"Error initializing database (ensure MariaDB is running and accessible): {e}")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
