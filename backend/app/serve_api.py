"""Container API entrypoint; exec preserves Uvicorn signal/shutdown handling."""
import os

from .runtime_policy import api_command


def main():
    command = api_command()
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
