from pydantic import BaseModel, ConfigDict


class TariffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int
