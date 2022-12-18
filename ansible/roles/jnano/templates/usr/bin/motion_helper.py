#!/usr/bin/python3 -u
# -u is needed to unbuffer print making everything go to syslog instantly 
import time 
import traceback
import subprocess
import os, io 
import argparse
import threading as th
import numpy as np 
from systemd import journal
import smtplib
from datetime import datetime, timedelta 


gmail_user = 'eusoubrasileiro@gmail.com'
gmail_app_password = {{ gmail_app_password | password_hash('sha512') }} 
sent_from = gmail_user
sent_to = ['aflopes7@gmail.com']
sent_subject = "Motion NVR Server ERROR"
email_text = f"""\
From: {sent_from}
To: {sent_to}
Subject: {sent_subject}

"""

   
def send_email(msg):
    sent_body = (msg)    
    email_text += sent_body + "\n"
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.ehlo()
        server.login(gmail_user, gmail_app_password)
        server.sendmail(sent_from, sent_to, email_text)
        server.close()    
    except Exception as exception:
        print("Error: %s!\n\n" % exception)

def send_email_if_errors():
    j = journal.Reader()
    j.log_level(journal.LOG_INFO)
    j.add_match(_SYSTEMD_UNIT="motion.service")
    j.seek_realtime(datetime.now() - timedelta(minutes=15))
    count=0
    msgs = []
    for entry in j:
        msgs.append(f" {entry['__REALTIME_TIMESTAMP']} {entry['MESSAGE']}")
        if '[ERR]' in entry['MESSAGE']:
            count=count+1  
    log_print(f"motion helper :: total number of [ERR] {count}")
    if count > 0:
        send_email("\n".join(msgs))
    return count 


# recommended approach dict as global
config = { 
    'motion_pictures_path' : None,
    'motion_movies_path' : None,
    'data_size' : 90.
    }

lock = th.Lock()
# only need to lock when printing on main or background threads

def log_print(*args, **kwargs):
    with lock:    
        # by default print on stdout -> go to syslog     
        print(time.strftime("%Y-%m-%d %H:%M:%S")," ".join(map(str,args)),**kwargs)

def recover_space():
    """run cleanning motion folders files reclaiming space used (older files first)
    """ 
    def array_files(storage_path):
        result = subprocess.run(r"find " + storage_path + r" -type f -printf '%T@;;%p;;%s\n'", 
            stdout=subprocess.PIPE, shell=True, universal_newlines=True)        
        data = np.loadtxt(io.StringIO(result.stdout), dtype=[('age', '<f8'),('path', 'U200'), ('size', 'i8')], delimiter=';;')
        data.sort(order='age') # big numbers last means younger files last
        data = data[::-1] #  (reverse it)
        return data 
    # look at movies and pictures folders, ignoring root due database file there
    data = np.concatenate([ array_files(config['motion_pictures_path']), 
            array_files(config['motion_movies_path']) ])
    space_max = config['data_size']*1024**3 # maximum size to bytes    
    sizes = np.cumsum(data['size']) # cumulative folder size starting with younger ones
    space_usage = sizes[-1]
    msg = 'motion helper :: data folders are {:.2f} GiB'.format(space_usage/(1024**3))
    if space_usage >= space_max : # only if folder bigger than maxsize 
        del_start = np.argmax(sizes >= space_max) # index where deleting should start             
        msg += ' :: recovering space. Deleting: {:} files'.format(len(sizes)-del_start)        
        for path in data['path'][del_start:]:            
            os.remove(path)
    log_print(msg)
    subprocess.run("find " + config['motion_pictures_path'] + " -type d -empty -delete", shell=True) # delete empty folders
    subprocess.run("find " + config['motion_movies_path'] + " -type d -empty -delete", shell=True) # delete empty folders
    # python pathlib or os is 1000x slower than find 
    # find saving timestamp, paths of files and size (recursive)
    # find /mnt/motion_data/pictures -type f -printf '%T@;;%p;;%s\n' 

def set_motion_config(dir_motion_data, data_size):
    """Sets the motion configuration files, paths 
    * motion_data: str
        sets `config['storage_path']`  -> target_dir (motion.conf)
    * data_size: float 
         sets `config['data_size']` maximum size folder to reclaim space
    """
    
    config['motion_pictures_path'] = os.path.join(dir_motion_data, 'pictures')
    config['motion_movies_path'] = os.path.join(dir_motion_data, 'movies')     
    config['data_size'] = data_size

    log_print("motion helper :: config options")
    for key, value in config.items():
        log_print(key, value)

def main():
    try:
        log_print('motion helper :: starting')
        # you can read syslog or log messages use events from motion.conf to get when thereis a disconnection or else    
        while True:            
            # takes almost forever to compute disk usage size so put on another thread  
            th.Thread(target=recover_space).start()             
            th.Thread(target=send_email_if_errors).start()             
            # I use syslog so I dont need to clean up self-made logs
            time.sleep(15*60) # every 15 minutes only
            # could change to events motion.conf
    except Exception as e:
        log_print("motion helper :: Python exception")
        log_print(traceback.format_exc())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Motion NVR Helper')
    parser.add_argument('-d','--data-path', help='Path to store videos and pictures (all data) -> target_dir (motion.conf)', required=True)    
    parser.add_argument('-m','--data-size', help='Maximum folder data size in GB to reclaim space (delete old)', required=False, default="550")
    args = parser.parse_args()
    set_motion_config(args.data_path, float(args.data_size))    
    main()
    
# rclone mount -vv nvr_remote:sda1 /home/android/nvr_dir --daemon 
