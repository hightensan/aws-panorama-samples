import sys
import os
import time
import datetime
import urllib
import json
import threading
import http.server
import ssl
import subprocess

sideloaded_dir = "./sideloaded"
#sideloaded_dir = "/opt/aws/panorama/storage/sideloaded"

panorama_default_dir = "/panorama"

entrypoints = [
    os.path.join( sideloaded_dir, "main.sh" ).replace("\\","/"),
    os.path.join( sideloaded_dir, "main.py" ).replace("\\","/"),
    os.path.join( panorama_default_dir, "main.sh" ).replace("\\","/"),
    os.path.join( panorama_default_dir, "main.py" ).replace("\\","/"),
]

python = "c:/Python39/python.exe"
#python = "python3.7"


class ApplicationProcessManager:

    p = None

    @staticmethod
    def run():

        if ApplicationProcessManager.p is not None:
            raise ValueError("Application process already exists.")

        for entrypoint in entrypoints:
            if os.path.exists(entrypoint):
                break
        else:
            raise ValueError("Entrypoint scrip not found.")

        dirname, filename = os.path.split(entrypoint)
        ext = os.path.splitext(filename)[1].lower()
        
        if ext == ".sh":
            cmd = [ "/bin/sh", filename ]
        elif ext == ".py":
            cmd = [ python, filename ]
        
        ApplicationProcessManager.p = subprocess.Popen( cmd, cwd=dirname )


    @staticmethod
    def kill():
        if ApplicationProcessManager.p is None:
            raise ValueError("Application process doesn't exist.")

        ApplicationProcessManager.p.kill()
        ApplicationProcessManager.p = None

class SideloadingRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    def do_GET(self):

        print( "GET :", self.path, flush=True )
        
        if self.path=="/files":
            
            filelist = []
            for place, dirs, files in os.walk( sideloaded_dir ):
                for filename in files:
                    
                    filepath = os.path.join( place, filename ).replace("\\","/")
                    assert filepath.startswith(sideloaded_dir)
                    filepath_relative = filepath[ len(sideloaded_dir) : ]
                    filepath_relative = filepath_relative.lstrip("/\\")
                    filepath_relative = filepath_relative.replace("\\","/")
                    
                    st = os.stat(filepath)
                    dt_mtime = datetime.datetime.fromtimestamp( st.st_mtime )
                    
                    filelist.append( {
                        "filepath" : filepath_relative,
                        "mtime" : dt_mtime.isoformat(),
                        "size" : st.st_size,
                    })

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()

            response_data = filelist
            response_data_s = json.dumps(response_data)
            response_data_b = response_data_s.encode("utf-8")

            self.wfile.write( response_data_b )
            
        else:
            self.send_response(404, "Resource doesn't exist")
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            
            message = "Resource Not found"
            message = message.encode("utf-8")

            self.wfile.write(message)

    def do_PUT(self):

        content_length = int(self.headers['Content-Length'])
        
        print( f"PUT : {self.path} : {content_length} bytes", flush=True )
        
        if self.path.startswith("/files/"):

            path = self.path[ len("/files/") : ]
            path = urllib.parse.unquote(path)

            dst_filename = os.path.join( sideloaded_dir, path.lstrip("/\\") ).replace("\\","/")
            print( f"Writing {dst_filename}" )
        
            # Write file
            with open( dst_filename, "wb" ) as dst_fd:
                d = self.rfile.read(content_length)
                print(f"Received {len(d)} bytes")
                dst_fd.write(d)

            # Update timestamp
            s_mtime = self.headers['mtime']
            dt_mtime = datetime.datetime.fromisoformat(s_mtime)
            st = os.stat(dst_filename)
            os.utime( dst_filename, times=( st.st_atime, dt_mtime.timestamp()) )

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
        
            response_data = {}
            response_data_s = json.dumps(response_data)
            response_data_b = response_data_s.encode("utf-8")

            self.wfile.write( response_data_b )

        else:
            pass
            # FIXME : 404

    def do_POST(self):

        print( "POST :", self.path, flush=True )
        
        if self.path=="/application":
        
            try:
                ApplicationProcessManager.run()
            except ValueError as e:
                print(e,flush=True)
                # FIXME : return error to cli
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
        
            response_data = {}
            response_data_s = json.dumps(response_data)
            response_data_b = response_data_s.encode("utf-8")

            self.wfile.write( response_data_b )
        
        else:
            pass
            # FIXME : 404

    def do_DELETE(self):

        print( f"DELETE : {self.path}", flush=True )

        if self.path.startswith("/files/"):

            path = self.path[ len("/files/") : ]
            path = urllib.parse.unquote(path)
        
            dst_filename = os.path.join( sideloaded_dir, path.lstrip("/\\") ).replace("\\","/")
            if os.path.exists(dst_filename):
                print( f"Deleting {dst_filename}" )
                os.unlink(dst_filename)
            else:
                print( f"Deleting file not found : {dst_filename}" )
        
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
        
            response_data = {}
            response_data_s = json.dumps(response_data)
            response_data_b = response_data_s.encode("utf-8")

            self.wfile.write( response_data_b )

        elif self.path.startswith("/application"):

            try:
                ApplicationProcessManager.kill()
            except ValueError as e:
                print(e,flush=True)
                # FIXME : return error to cli
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
        
            response_data = {}
            response_data_s = json.dumps(response_data)
            response_data_b = response_data_s.encode("utf-8")

            self.wfile.write( response_data_b )

        else:
            pass
            # FIXME : 404


class SideloadingAgent(threading.Thread):

    def __init__( self, port ):

        threading.Thread.__init__( self, name="SideloadingAgent", daemon=True )
        
        self.port = port

        self.is_canceled = False
        
    def run(self):

        print( "SideloadingAgent started", flush=True )

        ssl_context = ssl.create_default_context( purpose=ssl.Purpose.CLIENT_AUTH )

        # Server certificate & secret-key
        ssl_context.load_cert_chain( "./certs_keys/server.pem.cert", "./certs_keys/server.pem.key" )

        # Client certificate
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_verify_locations( "./certs_keys/client.pem.cert" )

        with http.server.HTTPServer(("", self.port), SideloadingRequestHandler) as httpd:
            httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
            httpd.serve_forever()

    def cancel(self):
        self.is_canceled = True

#---

def main():
    sideloading_agent = SideloadingAgent( port = 8123 )
    sideloading_agent.start()

    while True:
        time.sleep(1)

main()
