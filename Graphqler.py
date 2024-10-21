import sys
import os
import json
import requests
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter


def banner():
    print(f'''
  __     __     ______     ______   __     ______     __   __
 /\ \  _ \ \   /\  __ \   /\__  _\ /\ \   /\  __ \   /\ "-.\ \\
 \ \ \/ ".\ \  \ \  __ \  \/_/\ \/ \ \ \  \ \ \/\ \  \ \ \-.  \\
  \ \__/".~\_\  \ \_\ \_\    \ \_\  \ \_\  \ \_____\  \ \_\\"\_ \\
   \/_/   \/_/   \/_/\/_/     \/_/   \/_/   \/_____/   \/_/ \/_/
                https://github.com/TheWation/Graphqler
    ''')

class GraphqlObject:
    def __init__(self):
        self.name = ""
        self.ttype = ""
        self.args = []
        self.attrs = []
        self.values = []
        self.inputs = []
        self.return_type = None

class GraphqlArgument:
    def __init__(self):
        self.name = ""
        self.ttype = ""

def load_introspection(file_path):
    with open(file_path) as jfile:
        data = json.load(jfile)
    print("[~] Using introspection file for schema.\n")
    return data

def fetch_introspection(endpoint,session):
    introspection_query = '{"query":"query IntrospectionQuery{__schema{queryType{name} mutationType{name} subscriptionType{name} types{...FullType} directives{name description locations args {...InputValue}}}} fragment FullType on __Type{kind name description fields(includeDeprecated: true) {name description args {...InputValue} type {...TypeRef} isDeprecated deprecationReason} inputFields{...InputValue} interfaces{...TypeRef} enumValues(includeDeprecated: true) {name description isDeprecated deprecationReason} possibleTypes{...TypeRef}} fragment InputValue on __InputValue {name description type {...TypeRef} defaultValue} fragment TypeRef on __Type{kind name ofType {kind name ofType {kind name ofType {kind name}}}}"}'
    response = session.post(endpoint, json=json.loads(introspection_query))
    print("[~] Fetched schema from live endpoint.\n")
    return response.json()

def parse_type(type_info):
    """ Recursively parse the type information to get the final type name """
    if not type_info:
        return None
    if 'name' in type_info and type_info['name']:
        return type_info['name']
    elif 'ofType' in type_info:
        return parse_type(type_info['ofType'])
    return None

def parse_introspection(data):
    queries = []
    mutations = []
    types_dict = {}
    # Create a dictionary of types for easy lookup
    for v in data['data']['__schema']['types']:
        types_dict[v['name']] = v

    for v in data['data']['__schema']['types']:
        if v['name'] == 'Query' or v['name'] == 'Mutation':
            if 'fields' in v and isinstance(v['fields'], list) and len(v['fields']) > 0:
                for vv in v['fields']:
                    o = GraphqlObject()
                    o.name = vv['name']
                    o.ttype = 'QUERY' if v['name'] == 'Query' else 'MUTATION'
                    o.return_type = parse_type(vv['type'])

                    if 'args' in vv and isinstance(vv['args'], list) and len(vv['args']) > 0:
                        for vvv in vv['args']:
                            ttype = parse_type(vvv['type'])
                            arg = GraphqlArgument()
                            arg.name = vvv['name']
                            arg.ttype = ttype
                            o.args.append(arg)

                    if o.ttype == 'QUERY':
                        queries.append(o)
                    else:
                        mutations.append(o)

    return queries, mutations, types_dict

def display_details(item, types_dict):
    print(f"\n{item.ttype}: {item.name}")
    for arg in item.args:
        print(f"  Arg: {arg.name}, Type: {arg.ttype}")

    # Display return type details
    if item.return_type and item.return_type in types_dict:
        return_type_info = types_dict[item.return_type]
        print(f"\nReturn Type: {item.return_type}")
        if 'fields' in return_type_info and isinstance(return_type_info['fields'], list):
            for field in return_type_info['fields']:
                field_type = parse_type(field['type'])
                print(f"  Field: {field['name']}, Type: {field_type}")
    else:
        print("[-] Error: Return type not found in types dictionary.")


def select_fields(return_type, types_dict):
    """ Prompt user to select fields for a given return type """
    # Resolve the actual type if it's wrapped in List or Non-Null
    resolved_type = return_type
    while resolved_type not in types_dict:
        type_info = types_dict.get(resolved_type, {})
        if 'ofType' in type_info:
            resolved_type = parse_type(type_info['ofType'])
        else:
            break

    if resolved_type not in types_dict:
        print("[-] Error: Return type not found in types dictionary.")
        return ""

    return_type_info = types_dict[resolved_type]
    fields = return_type_info.get('fields', [])
    if not fields:
        #print("[-] Error: No fields available for this return type.")
        return ""

    field_names = [field['name'] for field in fields]

    print(f"\nAvailable fields for {resolved_type}: {', '.join(field_names)}")
    selected_fields_input = input("Enter fields to include (comma-separated): ").strip()

    selected_fields = []
    for field in selected_fields_input.split(','):
        field = field.strip()
        if field in field_names:
            # Check if the field is an object type and requires subfields
            field_type = next((f['type'] for f in fields if f['name'] == field), None)
            if field_type and parse_type(field_type) in types_dict:
                subfields = select_fields(parse_type(field_type), types_dict)
                selected_fields.append(f"{field} {{ {subfields} }}" if subfields else field)
            else:
                selected_fields.append(field)

    return " ".join(selected_fields)


def construct_graphql_query(item, args_input, fields_str):
    # Only add parentheses if there are arguments
    args_str = ", ".join([f"{k}: {json.dumps(v)}" for k, v in args_input.items()])
    if args_str:
        query = f"""
        {item.ttype.lower()} {{
            {item.name}({args_str}) {{
                {fields_str}
            }}
        }}
        """
    else:
        query = f"""
        {item.ttype.lower()} {{
            {item.name} {{
                {fields_str}
            }}
        }}
        """
    return query

def execute_graphql(endpoint, item, types_dict,session):
    print("\n[?] Do you want to create a query for this? (Y/n, default is no): ", end="")
    create_query = input().strip().lower() or "n"
    if create_query == 'y':
        # Construct the GraphQL query or mutation
        args_input = {}
        if item.args:
            for arg in item.args:
                value = input(f"[?] Enter value for {arg.name} ({arg.ttype}): ")
                # Convert to appropriate type
                if arg.ttype == "Int":
                    value = int(value)
                args_input[arg.name] = value

        # Prompt user to select fields
        fields_str = select_fields(item.return_type, types_dict)

        if not fields_str:
            print("[-] No fields selected. Please try again.")
            return

        query = construct_graphql_query(item, args_input, fields_str)

        # Ask if the user wants to send the request
        print("\n[?] Do you want to send this request? (y/N, default is no): ", end="")
        send_request = input().strip().lower() or "n"
        if send_request == 'y':
            print("Constructed GraphQL Query:")
            print(query)
            # Send the request
            response = session.post(endpoint, json={'query': query})
            response_json = response.json()
            print("\n[+] Response from server:")
            print(response_json)

            # Ask if the user wants to save the request and response
            print("\n[?] Do you want to save this request and response? (y/N, default is no): ", end="")
            save_logs_choice = input().strip().lower() or "n"
            if save_logs_choice == 'y':
                save_logs(query, response_json)
        else:
            # Ask if the user wants to see the query
            print("\n[?] Do you want to see the constructed query? (Y/n, default is yes): ", end="")
            show_query = input().strip().lower() or "y"
            if show_query == 'y':
                print("Constructed GraphQL Query:")
                print(query)

def save_logs(query, response):
    # Create logs directory if it doesn't exist
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Determine the next log ID
    existing_logs = [int(f.split('.')[0]) for f in os.listdir("logs") if f.endswith('.request.txt')]
    next_id = max(existing_logs) + 1 if existing_logs else 1

    # Save the request
    with open(f"logs/{next_id}.request.txt", "w", encoding='utf-8') as req_file:
        req_file.write(query)

    # Save the response with UTF-8 encoding
    with open(f"logs/{next_id}.response.json", "w", encoding='utf-8') as res_file:
        json.dump(response, res_file, ensure_ascii=False, indent=2)
        
def load_cookies(session, cookies):
    cookies_list = json.loads(open(cookies,'r').read())
    cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}
    session.cookies.update(cookies_dict)
    print("[*] Cookies loaded !")
    
def main(file_path=None, endpoint=None, proxy=None,cookies=None):
    request_session = requests.session()
    if cookies:
        load_cookies(request_session, cookies)
    if proxy:
        request_session.proxies = {
            "http": proxy,
            "https": proxy
        }
        print("[*] Proxy added !")
    if file_path:
        data = load_introspection(file_path)
    elif endpoint:
        data = fetch_introspection(endpoint,request_session)
    else:
        print("[-] Error: No introspection file or endpoint provided.")
        sys.exit(1)

    queries, mutations, types_dict = parse_introspection(data)

    # Debug: Print queries and mutations
    print("[+] Queries:", [q.name for q in queries])
    print("[+] Mutations:", [m.name for m in mutations])

    all_items = queries + mutations
    completer = WordCompleter([item.name for item in all_items], ignore_case=True)

    session = PromptSession()

    while True:
        try:
            user_input = session.prompt('[?] Select a query/mutation (or type "exit" to quit): ', completer=completer)
            if user_input.lower() == 'exit':
                break

            selected_items = [item for item in all_items if item.name == user_input]
            if selected_items:
                display_details(selected_items[0], types_dict)
                if endpoint:
                    execute_graphql(endpoint, selected_items[0], types_dict)
            else:
                print("[-] Invalid selection. Please try again.")
        except KeyboardInterrupt:
            continue  # Handle Ctrl+C gracefully
        except EOFError:
            break  # Exit on Ctrl+D

if __name__ == "__main__":

    banner()

    if len(sys.argv) < 2:
        print("Usage: python Graphqler.py [-f <introspection_file.json>] [-u <graphql_endpoint_url>] [-p <proxy>] [-c <cookies.json>]")
        sys.exit(1)

    ifile = None
    endpoint = None
    proxy = None
    cookies = None

    if '-f' in sys.argv:
        ifile_index = sys.argv.index('-f') + 1
        if ifile_index < len(sys.argv):
            ifile = sys.argv[ifile_index]

    if '-u' in sys.argv:
        endpoint_index = sys.argv.index('-u') + 1
        if endpoint_index < len(sys.argv):
            endpoint = sys.argv[endpoint_index]

    if '-c' in sys.argv:
        cookies_index = sys.argv.index('-c') + 1
        if cookies_index < len(sys.argv):
            cookies = sys.argv[cookies_index]
    if '-p' in sys.argv:
        proxy_index = sys.argv.index('-p') + 1
        if proxy_index < len(sys.argv):
            proxy = sys.argv[proxy_index]
            
    if not ifile and not endpoint:
        print("Error: No introspection file or endpoint provided.")
        sys.exit(1)

    main(ifile, endpoint,proxy,cookies)
