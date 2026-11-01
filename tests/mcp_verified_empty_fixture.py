# Integration snippet for mcp-server/server.py; not an installed server.
class SolidWorksVerifiedEmptyExitInput(BaseInput):
    process_id: int = Field(gt=0, lt=2**31, strict=True)
    expected_creation_filetime: int = Field(gt=116444736000000000, lt=2**63, strict=True)
    expected_executable_path: str = Field(min_length=1, max_length=32767, strict=True)
    expected_document_path: str = Field(min_length=1, max_length=32767, strict=True)
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    ownership_receipt_path: str = Field(min_length=1, max_length=32767, strict=True)
    ownership_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    empty_receipt_path: str = Field(min_length=1, max_length=32767, strict=True)
    empty_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    receipt_path: str = Field(min_length=1, max_length=32767, strict=True)
    wait_milliseconds: int = Field(default=10000, ge=1, le=30000, strict=True)
    acknowledge_exit_owned_empty_session: bool = Field(strict=True)
    acknowledge_restored_checkpoint_exit: bool = Field(strict=True)
    response_format: ResponseFormat = ResponseFormat.JSON

    @model_validator(mode="after")
    def verified_empty_exit_contract(self):
        from scripts.sw_owned_empty_exit import verified_empty_parameters
        verified_empty_parameters(self.model_dump(exclude={"response_format"}))
        return self


@mcp.tool(name="solidworks_exit_verified_empty_session", title="Exit Verified Empty SOLIDWORKS Session",
    annotations={"readOnlyHint":False,"destructiveHint":True,"idempotentHint":False,"openWorldHint":False})
def solidworks_exit_verified_empty_session(params: SolidWorksVerifiedEmptyExitInput) -> str:
    """One graceful ExitApp after checkpoint restore, pinned empty inspection and live process checks."""
    def op():
        if type(_selected_process_id) is not int or _selected_process_id != params.process_id:
            raise ValueError("Explicit owned process connection required")
        from scripts.sw_owned_empty_exit import safely_exit_verified_empty_session
        return safely_exit_verified_empty_session(params.model_dump(exclude={"response_format"}))
    return _run_locked(op, params.response_format, load_automation=False, desktop_guard=True)
