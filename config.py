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
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,        # Verifica conexion antes de usarla
        'pool_recycle': 300,           # Recicla conexiones cada 5 min
        'connect_args': {
            'connect_timeout': 10,     # Timeout de conexion 10 seg
        }
    }


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
