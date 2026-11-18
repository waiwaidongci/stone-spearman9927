from pydantic import BaseModel,Field
class SpecimenInput(BaseModel):
    source_key:str=Field(min_length=1,max_length=100)
    values:dict
ObservationInput=SpecimenInput
