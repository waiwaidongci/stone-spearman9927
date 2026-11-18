import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_tmp=tempfile.mkdtemp(prefix='stone-test-')
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///'+_tmp+'/test.db')
os.environ.setdefault('REDIS_URL','redis://localhost:6379/0')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('SEED_DEMO','false')
