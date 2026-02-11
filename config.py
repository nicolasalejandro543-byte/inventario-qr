import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuracion base."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'clave-secreta-desarrollo-cambiar-en-produccion'

    # Base de datos - Railway provee DATABASE_URL automaticamente
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///inventario.db')

    # Railway usa postgres:// pero SQLAlchemy necesita postgresql://
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Opciones de conexion para mayor resiliencia
    _engine_opts = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    # connect_timeout solo aplica para PostgreSQL, no SQLite
    if SQLALCHEMY_DATABASE_URI and 'postgresql' in SQLALCHEMY_DATABASE_URI:
        _engine_opts['connect_args'] = {'connect_timeout': 10}

    SQLALCHEMY_ENGINE_OPTIONS = _engine_opts


class DevelopmentConfig(Config):
    """Configuracion de desarrollo."""
    DEBUG = True


class ProductionConfig(Config):
    """Configuracion de produccion."""
    DEBUG = False


# Seleccionar configuracion segun entorno
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Obtiene la configuracion segun la variable de entorno."""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
