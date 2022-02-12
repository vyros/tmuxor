#!/usr/bin/env python


# =====================================================
# Author:   Vyros
# History:  January 2022 - Creation
# Version:  1.0.0 - Launch tmux with yaml configuration
# =====================================================


import getopt, json, re, statistics, subprocess, sys, yaml


class Session:

    attach = False
    session = None
    session_name = None
    windows_white_list = []

    def __init__(self, session: dict):

        self.session = session
        self.session_name = next(iter(session))
        session_exists = self.is_session_exists()

        if session_exists and self.is_session_killable():
            session_exists = False
            exec_tmux_and_return_code("kill-session", f"{self.session_name}")

        if not session_exists and not self.new_session():
            sys.exit(3)

        # Session exists
        self.attach = self.is_session_attachable()
        self.windows_list = Window.get_windows_list(self.session_name)

        for window in self.session[self.session_name]["windows"]:
            w = Window(self.session_name, window)
            if w.is_white_window():
                self.windows_white_list.append(w.get_name())

            w.resize_window()
            w.resize_panes()

        self.clean_session()
        self.focus_window()
        self.attach_session()

    def new_session(self) -> bool:
        return exec_bash_and_return_code(
            f"tmux new-session -d -s '{self.session_name}'"
        )

    def is_session_attachable(self) -> bool:
        key = "attach"
        return get_boolean(self.session[self.session_name], key)

    def is_session_exists(self):
        return exec_bash_and_return_code(f"tmux has-session -t '{self.session_name}'")

    def is_session_killable(self) -> bool:
        key = "kill-session"
        return get_boolean(self.session[self.session_name], key)

    def clean_session(self):
        if Window.is_window_killable(self.session[self.session_name]):
            for window in self.windows_list:
                window_index = next(iter(window))
                if window[window_index] not in self.windows_white_list:
                    exec_tmux_and_return_code(
                        "kill-window",
                        f"{self.session_name}:{window[window_index]}",
                    )

    def focus_window(self):
        exec_tmux_and_return_code(
            "select-window", f"{self.session_name}:{self.windows_white_list[0]}"
        )

    def attach_session(self):
        if self.attach:
            exec_tmux_and_return_code("attach", self.session_name)


class Window:

    resizep_commands = []
    resizew_commands = []
    session_name = None
    white_window = False
    window_name = None

    def __init__(self, session_name: str, window: dict):
        self.session_name = session_name
        self.window_name = next(iter(window))
        window_exists = self.is_window_exixts()

        if window_exists and self.is_window_killable(window[self.window_name]):
            window_exists = False
            exec_tmux_and_return_code(
                "kill-window", f"{session_name}:{self.window_name}"
            )

        elif window_exists and not self.is_window_killable(window[self.window_name]):
            self.white_window = True
            return

        if not window_exists and not self.new_window():
            sys.exit(4)

        # Window exists
        pane_index = 0
        variables = get_variables(window[self.window_name])
        self.white_window = True

        for pane in window[self.window_name]["panes"]:
            p = Pane(session_name, self.window_name, pane, pane_index, variables)
            if p.is_created():
                self.resizep_commands.append(p.get_size())
                pane_index += 1

        target = f"{session_name}:{self.window_name}"
        self.set_layout(window, target)

    def get_name(self):
        return self.window_name

    @staticmethod
    def get_windows_list(session_name):
        result_list = []
        result = parse_and_exec_bash_command(
            f"tmux lsw -t '{session_name}' 2>/dev/null | grep -Eo '(^[1-9]+:|\\n[1-9]+:)\s\w*'"  # | sed -e 's/^[1-9]:\s//g'"
        )
        result = parse_stdout(result.stdout).replace(" ", "").split("\n")
        for res in result:
            res = res.split(":")
            result_list.append({int(res[0]): str(res[1])})

        return result_list

    def is_white_window(self) -> bool:
        return self.white_window

    def is_window_exixts(self) -> bool:
        return exec_bash_and_return_code(
            f"tmux lsw -t '{self.session_name}' 2>/dev/null | grep -Ec '^[0-9]+:\s({self.window_name})[\*-]?\s+'"
        )

    @staticmethod
    def is_window_killable(entry: dict) -> bool:
        key = "kill-window"
        return get_boolean(entry, key)

    def new_window(self) -> bool:
        return exec_bash_and_return_code(
            f"tmux neww -t '{self.session_name}' -n '{self.window_name}'"
        )

    def resize_window(self):
        for resizew in self.resizew_commands:
            exec_bash_and_return_code(resizew)

    def resize_panes(self):
        for resizep in self.resizep_commands:
            exec_bash_and_return_code(resizep)

    def set_layout(self, window: dict, target: str):
        if "select-layout" in window[self.window_name]:
            self.resizew_commands.insert(
                0,
                get_tmux_command(
                    "select-layout",
                    target,
                    window[self.window_name][
                        "select-layout"
                    ],  # Should be an attachment
                ),
            )


class Pane:

    created = False
    pane_index = None
    pane_name = None
    resizep_command = None
    session_name = None
    window_name = None

    def __init__(
        self, session_name: str, window_name: str, pane: dict, pane_index, variables
    ):
        self.pane_index = pane_index
        self.pane_name = next(iter(pane))
        self.session_name = session_name
        self.window_name = window_name

        if pane_index == 0:
            self.created = True
        else:
            self.split()

        self.set_size(pane)
        self.start(pane, variables)

    def get_size(self):
        return self.resizep_command

    def is_created(self) -> bool:
        return self.created

    def new_pane(self):
        result = exec_bash_and_return_raw(
            f"tmux split-window -t {self.session_name}:{self.window_name}.{self.pane_index - 1}"
        )

        if result.returncode == 0:
            return True
        else:
            return parse_stdout(result.stderr)

    def set_size(self, pane):
        self.resizep_command = get_tmux_resizep_command(
            pane[self.pane_name]["commands"],
            f"{self.session_name}:{self.window_name}.{self.pane_index}",
        )

    def split(self):
        split_result = self.new_pane()
        if isinstance(split_result, str):
            log(f"{split_result} '{self.pane_name}'")
        else:
            self.created = True

    def start(self, pane, variables):
        parse_and_exec_commands(
            pane[self.pane_name]["commands"],
            f"{self.session_name}:{self.window_name}.{self.pane_index}",
            variables,
        )


def main(argv):
    global general

    inputfile = ""

    try:
        opts, args = getopt.getopt(
            argv, "ahi:n", ["attach", "help", "ifile=", "no-attach"]
        )
    except getopt.GetoptError as ex:
        print("Error: %s" % ex)
        usage()

    for opt, arg in opts:
        if opt in ("-a", "--attach"):
            attach = True
        elif opt in ("-h", "--help"):
            usage()
        elif opt in ("-i", "--ifile"):
            inputfile = arg
        elif opt in ("-n", "--no-attach"):
            attach = False

    inputyaml = get_yaml(inputfile)
    # jsonstring = json.dumps(inputyaml, sort_keys=True, indent=2)

    general = get_general(inputyaml)
    sessions = get_sessions(inputyaml)

    for session in sessions:
        s = Session(session)

    sys.exit(0)


def parse_and_exec_bash_command(command, variables=None, capture_output=True):

    result = subprocess.CompletedProcess(None, 0)
    variable_name = None

    if isinstance(command, dict):
        variable_name = next(iter(command))
        if variable_name not in variables:
            sys.exit(6)

        command = parse_command(command[variable_name], variables)

    if command is not None:
        result = subprocess.run(["bash", "-c", command], capture_output=capture_output)
        if variable_name is not None:
            result = parse_stdout(result.stdout).split("\n")[-1]
            variables[variable_name] = result

    return result


def exec_bash_and_return_code(command) -> bool:
    return True if parse_and_exec_bash_command(command).returncode == 0 else False


def exec_bash_and_return_raw(command) -> bool:
    return parse_and_exec_bash_command(command)


def exec_tmux_and_return_code(
    command: str, target: str, sub_command: str = "", attachment=None
):
    input_command = get_tmux_command(command, target, sub_command, attachment)
    return exec_bash_and_return_code(input_command)


def get_boolean(entry: dict, key: str) -> bool:
    if key in entry:
        return entry[key]
    return False


def get_general(config):
    return config["general"]


def get_sessions(config):
    return config["sessions"]


def get_tmux_command(
    command: str, target: str, sub_command: str = "", attachment=None
) -> str:
    command_attachment = (
        general["commands"][command] if command in general["commands"] else None
    )
    input_command = r"""tmux"""

    if isinstance(command_attachment, dict) and attachment is not None:
        for parameter in command_attachment:
            if parameter in attachment and len(parameter) == 1:
                command += f""" -{parameter} {attachment[parameter]}"""

    input_command += f""" {command} -t '{target}'"""

    if not sub_command == "":
        input_command += r" '" + sub_command + r"'"

    if isinstance(command_attachment, str) and not command_attachment == str(None):
        input_command += f""" {command_attachment}"""

    return input_command


def get_tmux_resizep_command(commands: dict, target: str):
    for command in commands:
        command_name = next(iter(command))

        if not command_name == "resizep":
            continue
        else:
            return get_tmux_command(
                command_name,
                target,
                attachment=command[command_name],
            )


def get_variables(window: dict) -> dict:
    if "variables" in window:
        return window["variables"]
    return {}


def get_yaml(file):
    try:
        with open(file, "r") as yamlfile:
            result = yaml.load(yamlfile, yaml.FullLoader)
        return result

    except FileNotFoundError as ex:
        print(ex)
        sys.exit(2)


def log(message):
    print(f"[!] {message.capitalize()}")


def parse_command(command: str, variables: dict) -> str:
    variables_key = "@v:"
    required_variables = re.findall(f"{variables_key}\w*", command)
    for rv in required_variables:
        vkey = rv.replace(variables_key, "")
        if vkey not in variables:
            sys.exit(5)

        if isinstance(variables[vkey], str) or isinstance(variables[vkey], int):
            command = command.replace(rv, str(variables[vkey]))

        elif (
            isinstance(variables[vkey], dict)
            and "bash" in variables[vkey]
            and isinstance(variables[vkey]["bash"], str)
        ):
            output = parse_stdout(
                parse_and_exec_bash_command(variables[vkey]["bash"]).stdout
            )
            command = command.replace(rv, output)

    return command


def parse_and_exec_commands(commands: dict, target: str, variables: list):
    for command in commands:
        command_name = next(iter(command))

        if command_name == "resizep":
            continue

        if command_name == "bash":
            parse_and_exec_bash_command(command[command_name], variables)
            continue

        if isinstance(command[command_name], list):
            for sub_command in command[command_name]:
                if isinstance(sub_command, str):
                    exec_tmux_and_return_code(
                        command_name, target, parse_command(sub_command, variables)
                    )
                elif isinstance(sub_command, dict):
                    sub_command_name = next(iter(sub_command))
                    if "pre-commands" in sub_command[sub_command_name]:
                        parse_and_exec_commands(
                            sub_command[sub_command_name]["pre-commands"],
                            target,
                            variables,
                        )
                    exec_tmux_and_return_code(
                        command_name, target, parse_command(sub_command_name, variables)
                    )
                    if "post-commands" in sub_command[sub_command_name]:
                        parse_and_exec_commands(
                            sub_command[sub_command_name]["post-commands"],
                            target,
                            variables,
                        )

        elif isinstance(command[command_name], dict):
            exec_tmux_and_return_code(
                command_name,
                target,
                attachment=command[command_name],
            )

        elif isinstance(command[command_name], str):
            exec_tmux_and_return_code(
                command_name,
                target,
                parse_command(command[command_name], variables),
            )


def parse_stdout(stdout):
    return str(stdout.decode("utf-8")).strip("\n")


def usage():
    print("Usage: %s -i <inputfile>" % sys.argv[0])
    sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])

sys.exit(0)
