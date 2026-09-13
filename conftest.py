import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import _sqlalchemy_stub
_sqlalchemy_stub.install()
