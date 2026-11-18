from sqlalchemy import Column,Integer,String,Text
from src.config.database import Base
class MaterialBatch(Base):
    __tablename__='studies'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),unique=True,nullable=False)
    source_filename=Column(String(120),nullable=False)
    description=Column(Text,default='')
Study=MaterialBatch
