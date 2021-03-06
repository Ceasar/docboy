"""
This script encourages documentation in a codebase.

This script will:

- Find undocumented public methods
- Find who wrote that method
- Email that person politely asking them to fix their code

This script is multithreaded to reduce the cost of blocking operations
over large codebases.


To test this code, a debug mail server can be run with:

    python -m smtpd -n -c DebuggingServer localhost:1025
"""
import os
import re
import smtplib
import subprocess
from email.mime.text import MIMEText
from Queue import Queue
from threading import Thread, RLock

# Whether or not to actually send emails
DRY_RUN = False

# Delimiter used to detect whether or not a method is commented
COMMENT_END = "*/"

# Regex to extract email from git blames
EXTRACT_EMAIL_PATTERN = re.compile(r"^author-mail <(.+)>$")

# The sender of the email
ME = "ceasar@fb.com"

_NUM_WORKER_THREADS = 4


def _raw_run(args, log_output=False):
    """Run a command and capture its output."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout.read()


def get_blame(filename, line_number, local_path="."):
    """Get the email of the person responsible for the given line."""
    args = [
        "git",
        "blame",
        "-p",  # show porcelain
        "-l",  # show long revision
        os.path.join(local_path, filename),
        "-L",  # line number
        "%d,+1" % line_number,
    ]
    blame = _raw_run(args)
    if blame is None:
        raise ValueError("Could not execute `git blame`. Is this a git repo?")
    else:
        return blame


def gen_undocumented_public_methods(filename):
    """Find all undocumented public methods in class.

    A method is considered documented if the line preceding the definition
    is COMMENT_END.

    A method is considered public if the definition begins with 'public'.
    """
    has_comment = False
    with open(filename) as f:
        for linenum, line in enumerate(f):
            stripped = line.strip()
            if stripped == COMMENT_END:
                has_comment = True
            else:
                if not has_comment:
                    tokens = stripped.split()
                    if len(tokens) > 0 and tokens[0] == "public":
                        if "function" in tokens:
                            if not any(t.startswith("__") for t in tokens):
                                yield linenum, line
                has_comment = False


def build_email(me, you, subject, body):
    """Build an email.

    :param me == the sender's email address
    :param you == the recipient's email address
    :param subject == the subject of the message
    :param body == the message to send
    """
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = me
    msg['To'] = you
    return msg


def build_message(recipient_name, filename, line_number):
    """Build a polite message requesting documentation."""
    return """
    Hi %s,

    You are receiving this email because the function declared in %s, line number %s, needs documentation. (see: https://phabricator.fb.com/diffusion/E/browse/tfb/trunk/%s)

    Remember, at Facebook, we believe that a more open world is a better world because people with more information can make better decisions and have a greater impact. That goes for running our company as well. We work hard to make sure everyone at Facebook has access to as much information as possible about every part of the company so they can make the best decisions and have the greatest impact.

    Sincerely,
    Ceasar Bautista
    """ % (recipient_name, filename, line_number, filename)


def _start_daemons(target, count):
    """Start a number of daemons on a process."""
    for _ in range(count):
        t = Thread(target=target)
        t.daemon = True
        t.start()


def main():
    """Dispatch emails asking people to document undocumented code."""
    try:
        server = smtplib.SMTP('localhost')
    except:
        # try debug server
        server = smtplib.SMTP('localhost', 1025)

    blames = Queue()
    lines = Queue()
    filenames = Queue()
    lock = RLock()

    def fileworker():
        while True:
            filename = filenames.get()
            for line_number, _ in gen_undocumented_public_methods(filename):
                lines.put((filename, line_number))
            filenames.task_done()

    def blameworker():
        while True:
            filename, line_number = lines.get()
            blame = get_blame(filename, line_number)
            blames.put((blame, filename, line_number))
            lines.task_done()

    def mailworker():
        while True:
            blame, filename, line_number = blames.get()
            for line in blame.split("\n"):
                match = EXTRACT_EMAIL_PATTERN.match(line)
                if match:
                    email = match.group(1)
                    break
            recipient, filename = email.split('@')[0], 'www' + filename[1:]
            mail = build_email(ME, email, 'Please document your code',
                               build_message(recipient, filename, line_number))
            if DRY_RUN:
                print mail.as_string()
                print "-" * 80
            else:
                with lock:
                    server.sendmail(ME, [email], mail.as_string())
            blames.task_done()

    try:
        for path, dirs, files in os.walk('.'):
            for file in files:
                filename = os.path.join(path, file)
                if filename.endswith(".php"):
                    filenames.put(filename)
        _start_daemons(fileworker, _NUM_WORKER_THREADS)
        _start_daemons(blameworker, _NUM_WORKER_THREADS)
        _start_daemons(mailworker, _NUM_WORKER_THREADS)
        filenames.join()
        lines.join()
        blames.join()
    finally:
        server.quit()

if __name__ == "__main__":
    main()
