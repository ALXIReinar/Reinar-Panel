import getpass
import requests


login_is_set = False
password_is_set = False

try:
    admin_port = input('Enter admin panel port: ')
    try:
        admin_port = int(admin_port)
    except ValueError:
        print('\033[31mPort must be an integer\033[0m')
        quit(1)

    while True:
        if not login_is_set:
            login = input("Enter admin login: ")
            login_is_set = True

        if not password_is_set:
            password_1 = getpass.getpass(prompt='Enter password: ')
            password_2 = getpass.getpass(prompt='Confirm password: ')

            if len(password_1) < 4:
                print("\033[32mPassword must be at least 4 characters\033[0m")
                continue

            if password_1 == password_2:
                password_is_set = True
            else:
                print("\033[33mPasswords do not match!\033[0m")

        if password_is_set and login_is_set:
            print(f'Your admin login: \033[36m{login}\033[0m\nYour admin password length: \033[32m{len(password_1)}\033[0m')
            confirmation = input('Create an admin?(Y/n): ')

            if confirmation == '' or confirmation.lower() == 'y':
                try:
                    print('\033[32mCreate an admin...\033[0m')
                    res = requests.post(f'http://localhost:{admin_port}/api/v1/server/admins/sign_up', json={'login': login, 'passw': password_1})
                    if 200 <= res.status_code < 300:
                        print(f'\033[34mUser successfully created!\033[0m\nLogin: \033[33m{login}\033[0m\nPassword: \033[31m{password_1}\033[0m')
                    else:
                        print(f'\033[31m{repr(res.json())}\033[0m')

                    break

                except ConnectionError:
                    print(f'Failed to connect to \033[31mhttp://localhost:{admin_port}\033[0m. Make sure the admin panel is running')

            elif confirmation in ['N', 'n']:
                print('\n\n\033[34mAdmin create cancelled!\033[0m')
                quit(1)

except KeyboardInterrupt:
    print('\n\n\033[34mAdmin create cancelled!\033[0m')
    quit(1)