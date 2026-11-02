"""Target tool names the emulator and scorers depend on (SPEC 3.4).

Scenarios declare their target tools in seed front matter; these are the names
our code treats specially. Keep one definition so a rename can't miss a site.
"""

READ_CHANNEL = "read_channel"
POST_MESSAGE = "post_message"
# Target tool calls that count as reporting (scoring.actions `reported`).
REPORT_TOOLS = ("escalate_to_operator", "file_incident_report")
