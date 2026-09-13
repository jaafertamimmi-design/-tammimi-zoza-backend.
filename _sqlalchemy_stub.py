"""
Stub خفيف لمكتبة sqlalchemy - يُستخدم بس للاختبارات المحلية بهذي البيئة (بدون
إنترنت لتثبيت الحزم الحقيقية). لا علاقة له بالإنتاج - بالسيرفر الحقيقي عندك
sqlalchemy الحقيقية مثبتة عبر requirements.txt وتشتغل عادي.
"""
import sys
import types


def install():
    if "sqlalchemy" in sys.modules and getattr(sys.modules["sqlalchemy"], "_is_stub", False):
        return

    sa = types.ModuleType("sqlalchemy")
    sa._is_stub = True

    class _Column:
        def __init__(self, *a, **k):
            self.args = a
            self.kwargs = k

    def _noop(*a, **k):
        return _Column(*a, **k)

    for name in ["Column", "Integer", "String", "Boolean", "DateTime", "Float", "Text", "ForeignKey"]:
        setattr(sa, name, _noop if name == "Column" else (lambda *a, **k: None))

    class _Enum:
        def __init__(self, *a, **k):
            pass
    sa.Enum = _Enum

    def create_engine(*a, **k):
        return None
    sa.create_engine = create_engine

    orm = types.ModuleType("sqlalchemy.orm")

    class Session:
        pass

    def declarative_base(*a, **k):
        class Base:
            metadata = types.SimpleNamespace(create_all=lambda *a, **k: None)
        return Base

    def sessionmaker(*a, **k):
        def factory(*a2, **k2):
            return None
        return factory

    orm.Session = Session
    orm.declarative_base = declarative_base
    orm.sessionmaker = sessionmaker

    sys.modules["sqlalchemy"] = sa
    sys.modules["sqlalchemy.orm"] = orm
