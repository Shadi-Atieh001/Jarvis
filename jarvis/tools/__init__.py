"""JARVIS tools. Every .py file in this folder is loaded at startup.

To add a tool, create a new file here:

    from jarvis.core.tools import tool, ToolResult

    @tool(
        name="say_hello",
        description="Greets someone by name.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        tier="auto",        # auto | confirm | blocked
        read_only=True,     # True if it changes nothing
    )
    def say_hello(args, ctx):
        return f"Hello, {args['name']}."

Files whose names start with an underscore are ignored.
"""
