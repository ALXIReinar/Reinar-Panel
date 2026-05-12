from pydantic import BaseModel, IPvAnyAddress, Field


class RemoteExecBaseSchema(BaseModel):
    private_ip: IPvAnyAddress
    api_port: int = Field(gt=0, le=65535)

class ExecCMDNodeSchema(RemoteExecBaseSchema):
    cmd: str = Field(..., min_length=1, max_length=200)
