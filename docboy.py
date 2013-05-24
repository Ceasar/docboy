"""
This script encourages documentation in a codebase.

This script will:

- Find undocumented public methods
- Find who wrote that method
- Email that person politely asking them to fix their code

This script is multithreaded to reduce the cost of blocking operations
over large codebases.

"""
import os
import re
import smtplib
import subprocess
from email.mime.text import MIMEText
from Queue import Queue
from threading import Thread, RLock


ME = "ceasar@fb.com"
COMMENT_END = "*/"
EXTRACT_EMAIL_PATTERN = re.compile(r"^author-mail <(.+)>$")

_NUM_WORKER_THREADS = 4


def _raw_run(args, log_output=False):
    """Run a command and capture its output."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.stdout.read()
    return out


def blame(filename, line_number, local_path="."):
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
    output = _raw_run(args)

    for line in output.split("\n"):
        match = EXTRACT_EMAIL_PATTERN.match(line)
        if match:
            return match.group(1)
    raise ValueError("Could not execute `git blame`. Is this a git repo?")


def get_undocumented_public_methods(filename):
    """Find all undocumented public methods in class.

    A method is considered documented if the line preceding the definition
    is '*/'.

    A method is considered public if the defintiion begins with 'public'.
    """
    has_comment = False
    with open(filename) as f:
        lines = enumerate(f.readlines())
        for linenum, line in lines:
            if line.strip() == COMMENT_END:
                has_comment = True
            else:
                tokens = line.strip().split()
                if len(tokens) > 0 and tokens[0] == "public":
                    if has_comment:
                        pass
                    else:
                        yield linenum, line
                has_comment = False


def build_email(me, you, subject, body):
    """
    Build an email.

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


def build_message(recipient, filename, line_number):
    """Send a polite email requesting documentation."""
    username = recipient.split('@')[0]
    filename = 'www' + filename[1:]
    # subject = "Please document your code"
    body = """
    Hi %s,

    You are receiving this email because the function declared in %s, line number %s, needs documentation. (see: https://phabricator.fb.com/diffusion/E/browse/tfb/trunk/%s)

    Remember that at Facebook, we believe that a more open world is a better world because people with more information can make better decisions and have a greater impact. That goes for running our company as well. We work hard to make sure everyone at Facebook has access to as much information as possible about every part of the company so they can make the best decisions and have the greatest impact.

    Sincerely,
    Ceasar Bautista
    """ % (username, filename, line_number, filename)
    return body


def main():
    try:
        server = smtplib.SMTP('localhost')
    except:
        server = smtplib.SMTP('localhost', 1025)

    emails = Queue()
    blames = Queue()
    filenames = Queue()
    lock = RLock()

    def fileworker():
        filename = filenames.get()
        for line_number, _ in get_undocumented_public_methods(filename):
            blames.put((filename, line_number))
        filenames.task_done()

    def blameworker():
        filename, line_number = blames.get()
        email = blame(filename, line_number)
        emails.put((email, line_number))
        blames.task_done()

    def mailworker():
        email, line_number = emails.get()
        mail = build_email(ME, email, 'Please document your code',
                           build_message(email, filename, line_number))
        msg = mail.as_string()
        with lock:
            server.sendmail(ME, [email], msg)
        emails.task_done()

    try:
        for path, dirs, files in os.walk('.'):
            for file in files:
                filename = os.path.join(path, file)
                if filename.endswith(".php"):
                    filenames.put(filename)
        for _ in range(_NUM_WORKER_THREADS):
            t = Thread(target=fileworker)
            t.daemon = True
            t.start()
        for _ in range(_NUM_WORKER_THREADS):
            t = Thread(target=blameworker)
            t.daemon = True
            t.start()
        for _ in range(_NUM_WORKER_THREADS):
            t = Thread(target=mailworker)
            t.daemon = True
            t.start()
        filenames.join()
        blames.join()
        emails.join()
    finally:
        server.quit()

if __name__ == "__main__":
    main()
