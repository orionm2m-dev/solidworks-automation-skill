# Add the new model and tool; no existing public action is changed.
class SolidWorksShallowGuideDefinitionsInput(BaseInput):
    process_id: int = Field(gt=0,lt=2**31,strict=True)
    expected_document_path: str = Field(min_length=1,max_length=32767,strict=True)
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$",strict=True)
    expected_configuration: str = Field(min_length=1,max_length=256,strict=True)
    addin_clsid: str = Field(min_length=38,max_length=38,strict=True)
    checkpoint_receipt_path: str = Field(min_length=1,max_length=32767,strict=True)
    checkpoint_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$",strict=True)
    session_rebind_receipt_path: str = Field(min_length=1,max_length=32767,strict=True)
    session_rebind_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$",strict=True)
    choices: dict = Field(strict=True)
    module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$",strict=True)
    receipt_path: str = Field(min_length=1,max_length=32767,strict=True)
    acknowledge_definition_only_group: bool = Field(strict=True)
    response_format: ResponseFormat = ResponseFormat.JSON

    @model_validator(mode="after")
    def exact_definition_group(self):
        from scripts.sw_cam_guide_group_definitions import validate_request
        validate_request(dict(action='insert_shallow_guide_definitions',params=self.model_dump(exclude={'response_format'})))
        return self


@mcp.tool(name='solidworks_cam_insert_shallow_guide_definitions',title='Insert Four Shallow Guide Definitions',
    annotations={'readOnlyHint':False,'destructiveHint':True,'idempotentHint':False,'openWorldHint':False})
def solidworks_cam_insert_shallow_guide_definitions(params: SolidWorksShallowGuideDefinitionsInput) -> str:
    """Insert four exact MILL definitions with own NC readback; no SetTool/GTP/Save."""
    def op():
        if type(_selected_process_id) is not int or _selected_process_id != params.process_id:
            raise ValueError('Explicit current owned process connection required')
        from scripts.sw_cam_guide_group_definitions import dispatch_request
        return dispatch_request(dict(action='insert_shallow_guide_definitions',params=params.model_dump(exclude={'response_format'})))
    return _run_locked(op,params.response_format,load_automation=False,desktop_guard=True)
