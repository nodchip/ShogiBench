import argparse
import hashlib
import os
import re
import requests

# Basic Information:
# Test options must contain 'Threads={} Hash={}'
# Test Modes may either be of type 'SPRT' or 'GAMES'
# Syzygy settings are { 'OPTIONAL', 'REQUIRED', 'DISABLED' }
# Max Games is ignored unless test is of type 'GAMES'
# Networks must be assigned using their SHA256, not their name
# Networks with the value '' are used for tests without Networks


def url_join(*args):
    # Join a set of URL paths while maintaining the correct format
    return '/'.join([f.lstrip('/').rstrip('/') for f in args]) + '/'


def create_test():

    # We can use ENV variables for Username, Password, and Server
    req_user = required = "OPENBENCH_USERNAME" not in os.environ
    req_pass = required = "OPENBENCH_PASSWORD" not in os.environ
    req_server = required = "OPENBENCH_SERVER" not in os.environ

    # For clarity, seperate out this help text
    help_user = (
        "Username. May also be passed as OPENBENCH_USERNAME environment variable"
    )
    help_pass = (
        "Password. May also be passed as OPENBENCH_PASSWORD environment variable"
    )
    help_server = (
        "  Server. May also be passed as OPENBENCH_SERVER   environment variable"
    )

    # Parse all arguments, all of which must exist in some form
    p = argparse.ArgumentParser()
    p.add_argument("-U", "--username", help=help_user, required=req_user)
    p.add_argument("-P", "--password", help=help_pass, required=req_pass)
    p.add_argument("-S", "--server", help=help_server, required=req_server)

    p.add_argument("--dev_engine", help="Dev Engine", required=True)
    p.add_argument("--dev_repo", help="Dev Source", required=True)
    p.add_argument("--base_engine", help="Base Engine", required=True)
    p.add_argument("--base_repo", help="Base Source", required=True)

    p.add_argument("--dev_branch", help="Dev Branch", required=True)
    p.add_argument("--dev_bench", help="Dev Bench", required=True)
    p.add_argument("--dev_network", help="Dev Network", required=True)
    p.add_argument("--dev_book", help="Dev Book", default="")
    p.add_argument("--dev_options", help="Dev Options", required=True)
    p.add_argument("--dev_time_control", help="Dev Time", required=True)

    p.add_argument("--base_branch", help="Base Branch", required=True)
    p.add_argument("--base_bench", help="Base Bench", required=True)
    p.add_argument("--base_network", help="Base Network", required=True)
    p.add_argument("--base_book", help="Base Book", default="")
    p.add_argument("--base_options", help="Base Options", required=True)
    p.add_argument("--base_time_control", help="Base Time", required=True)

    p.add_argument("--test_mode", help="Test Mode", required=True)
    p.add_argument("--test_bounds", help="Bounds", required=True)
    p.add_argument("--test_confidence", help="Confidence", required=True)

    p.add_argument("--book_name", help="Opening Book", required=True)
    p.add_argument("--upload_pgns", help="Upload PGNs", required=True)
    p.add_argument("--priority", help="Priority", required=True)
    p.add_argument("--throughput", help="Throughput", required=True)
    p.add_argument("--workload_size", help="Workload Size", required=True)
    p.add_argument("--syzygy_wdl", help="Syzygy WDL", required=True)

    p.add_argument("--syzygy_adj", help="Syzygy ADJ.", required=True)
    p.add_argument("--win_adj", help="Win ADJ.", required=True)
    p.add_argument("--draw_adj", help="Draw ADJ.", required=True)

    p.add_argument("--scale_method", help="Scale Method", required=True)
    p.add_argument("--scale_nps", help="Expected NPS", required=True)

    args = p.parse_args()

    # Fallback on ENV variables for Username, Password, and Server
    args.username = args.username if args.username else os.environ["OPENBENCH_USERNAME"]
    args.password = args.password if args.password else os.environ["OPENBENCH_PASSWORD"]
    args.server = args.server if args.server else os.environ["OPENBENCH_SERVER"]

    # All scripts connect through this API point, with an action in the POST data
    url = url_join(args.server, "scripts")

    with open(args.dev_network, "rb") as network:
        dev_network_sha256 = hashlib.sha256(network.read()).hexdigest()[:8].upper()

    with open(args.base_network, "rb") as network:
        base_network_sha256 = hashlib.sha256(network.read()).hexdigest()[:8].upper()

    # POST payload must contain an action value
    data = {
        "username": args.username,
        "password": args.password,
        "dev_engine": args.dev_engine,
        "dev_repo": args.dev_repo,
        "base_engine": args.base_engine,
        "base_repo": args.base_repo,
        "dev_branch": args.dev_branch,
        "dev_bench": args.dev_bench,
        "dev_network": dev_network_sha256,
        "dev_book": args.dev_book,
        "dev_options": args.dev_options,
        "dev_time_control": args.dev_time_control,
        "base_branch": args.base_branch,
        "base_bench": args.base_bench,
        "base_network": base_network_sha256,
        "base_book": args.base_book,
        "base_options": args.base_options,
        "base_time_control": args.base_time_control,
        "test_mode": args.test_mode,
        "test_bounds": args.test_bounds,
        "test_confidence": args.test_confidence,
        "book_name": args.book_name,
        "upload_pgns": args.upload_pgns,
        "priority": args.priority,
        "throughput": args.throughput,
        "workload_size": args.workload_size,
        "syzygy_wdl": args.syzygy_wdl,
        "syzygy_adj": args.syzygy_adj,
        "win_adj": args.win_adj,
        "draw_adj": args.draw_adj,
        "scale_method": args.scale_method,
        "scale_nps": args.scale_nps,
        "action": "CREATE_TEST",
    }

    # Upload the file and report the status code
    print(data)
    r = requests.post(url, data=data)
    print("Code  : %s" % (r.status_code))

    # Report any error messages
    pattern = r'<div class="error-message">\s*<pre>(.*?)</pre>\s*</div>'
    if matches := re.findall(pattern, r.text, re.DOTALL):
        print("Error : %s" % (matches[0].strip()))

    # Report any status messages
    pattern = r'<div class="status-message">\s*<pre>(.*?)</pre>\s*</div>'
    if matches := re.findall(pattern, r.text, re.DOTALL):
        print("Status: %s" % (matches[0].strip()))


if __name__ == "__main__":
    create_test()
