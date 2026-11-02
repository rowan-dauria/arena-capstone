"""Target tool names the emulator and scorers depend on (SPEC 3.4).

Scenarios declare their target tools in seed front matter; these are the names
our code treats specially. Keep one definition so a rename can't miss a site.
"""

READ_CHANNEL = "read_channel"
POST_MESSAGE = "post_message"
# Target tool calls that count as reporting (scoring.actions `reported`).
REPORT_TOOLS = ("escalate_to_operator", "file_incident_report")
# Target repo tools answered by code (emulator.repo_tools), never by the auditor,
# in scenarios whose seed has a `repo` block.
REPO_TOOLS = ("list_files", "read_file", "write_file", "run_ci", "git_log", "sign_off")
