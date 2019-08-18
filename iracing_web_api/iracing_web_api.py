import requests
import re
import json
import urllib.parse

IRACING_LOGIN = 'https://members.iracing.com/membersite/Login'
IRACING_FRIENDS= "http://members.iracing.com/membersite/member/GetDriverStatus?friends=1&studied=1&blacklisted=1"
IRACING_HOME = "https://members.iracing.com/membersite/member/Home.do"
IRACING_PRACTICE_SUBSESSIONS = "https://members.iracing.com/membersite/member/GetOpenSessions?season={series_id}&invokedby=seriessessionspage"
IRACING_OPENSESSION_DRIVERS = "https://members.iracing.com/membersite/member/GetOpenSessionDrivers?subsessionid={subsession}&requestindex=0"
IRACING_SESSION_DRIVERS = "https://members.iracing.com/membersite/member/GetSessionDrivers?subsessionid={subsession}&requestindex=0"
IRACING_WATCH_SUBSESSIONS = "https://members.iracing.com/membersite/member/GetSpectatorSessions?type=road"
IRACING_EVENT_PAGE = "https://members.iracing.com/membersite/member/EventResult.do?&subsessionid={subsession}"
IRACING_SUBSESSION_DRIVER_LAPS = "https://members.iracing.com/membersite/member/GetLaps?&subsessionid={subsession}&groupid={custid}&simsesnum=0"

class LoginFailed(Exception):
    pass

class iRacingClient:
    
    def __init__(self, username, password):
        self.session = requests.session()
        credentials = { "username": username, "password": password }
        response = self.session.post(IRACING_LOGIN, data=credentials)
        if response.url == "https://members.iracing.com:443/membersite/failedlogin.jsp":
            raise LoginFailed

    def driver_status(self):
        friend_data = self.friend_data()
        session_data = self.session_data()
        driver_status = {}
        for driver in friend_data:
            if driver in session_data:
                driver_status[driver] = session_data[driver]
            else:
                driver_status[driver] = None
        return driver_status

    def subsession_results(self, subsession):
        url = IRACING_EVENT_PAGE.format(subsession=subsession)
        text = self.session.get(url).text
        found = re.findall(r"var\sresultOBJ\s*=\s*{([\S\s]*?)};", text)
        cleaned = [clean(x) for x in found]
        drivers = [make_dict(x) for x in cleaned]
        drivers = [driver for driver in drivers if driver['simSesName'] == "\"RACE\""]
        
        grid = {}
        all_lap_times = []

        for driver in drivers:
            name = get_name(driver['displayName'])
            irating = driver['newiRating']
            custid = driver['custid']
            pos = driver['finishPos']
            laps_url = IRACING_SUBSESSION_DRIVER_LAPS.format(subsession=subsession, custid=custid)
            response = self.session.get(laps_url)

            laps = response.json()['lapData']
            lap_arr = []
            
            for a, b in zip(laps[1:], laps[2:]):
                lap_flags = int(b['flags'])
                if not bool(lap_flags & 3):
                    # lap is valid and no tow occured
                    delta = (b['ses_time'] - a['ses_time']) / 10000
                    all_lap_times.append(delta)
                    lap_arr.append(delta)

                
                
            grid[name] = {'irating': irating, 'custid': custid, 'pos': pos, 'laps': lap_arr}
        
        return grid, all_lap_times
        
    def friend_data(self):
        response = self.session.get(IRACING_FRIENDS)
        data = response.json()

        friend_data = {}
        for driver in data['fsRacers']:
            name = unquote(driver['name'])
            friend_data[name] = currently_driving(driver)

        return friend_data

    def session_data(self):
        session_data = {}
        series = self.series()

        # Practice sessions
        subsessions = {}
        for series_id, series_name in series.items():
            for subsession, event_type in self.practice_subsessions(series_id).items():
                subsessions[subsession] = {'series_id': series_id, 'series_name': series_name, 'event_type': event_type }
        
        for subsession, info in subsessions.items():
            for driver in self.open_session_drivers(subsession):
                session_data[driver] = info

        # Watch sessions
        subsessions = self.watch_subsessions(series)
        for subsession, info in subsessions.items():
            for driver in self.session_drivers(subsession):
                session_data[driver] = info

        return session_data

    def series(self):
        response = self.session.get(IRACING_HOME)
        text = response.text
        found = re.findall(r"var\sAvailSeries\s*=\s*extractJSON\('([\S\s]*?)'\);", text)
        data = json.loads(found[0])
        series = {}
        for entry in data:
            if entry['category'] == 2:
                series[entry['seasonid']] = unquote(entry['seriesname'])

        return series

    def practice_subsessions(self, series_id):
        url = IRACING_PRACTICE_SUBSESSIONS.format(series_id=series_id)
        response = self.session.get(url)
        data = response.json()
        return { el['15']: 'Practice' for el in data['d'] }

    def watch_subsessions(self, series):
        response = self.session.get(IRACING_WATCH_SUBSESSIONS)
        data = response.json()
        subsessions = {}
        for el in data:
            subsession_id = el['subsessionid']
            series_id = el['seasonid']
            series_name = series[series_id]
            if el['evttype'] == 2:
                event_type = 'Practice'
            elif el['evttype'] == 5:
                event_type = 'Race'
            elif el['evttype'] == 4:
                event_type = 'Time Trial'
            else:
                event_type = 'Other'

            subsessions[subsession_id] = {'series_id': series_id, 'series_name': series_name, 'event_type': event_type }

        return subsessions

    def open_session_drivers(self, subsession):
        url = IRACING_OPENSESSION_DRIVERS.format(subsession=subsession)
        response = self.session.get(url)
        data = response.json()
        return [unquote(el['dn']) for el in data['rows']]

    def session_drivers(self, subsession):
        url = IRACING_SESSION_DRIVERS.format(subsession=subsession)
        response = self.session.get(url)
        data = response.json()
        return [unquote(el['dn']) for el in data['rows']]


def currently_driving(driver_data):
    return 'sessionStatus' in driver_data and driver_data['sessionStatus'] != 'none'


def unquote(s):
    s = s.replace('+', ' ')
    return urllib.parse.unquote(s)

def clean(text):
    text = text.replace('\n', '')
    text = text.replace('\t', '')
    text = text.replace('\r', '')
    text = text.replace("\'", "\"")
    return text

def make_dict(s):
    pairs = [x.split(":") for x in s.split(",")]
    drivers = {}
    for pair in pairs:
        if len(pair) == 2:
            drivers[pair[0]] = pair[1]
    return drivers

def get_name(s):
    start = s.find("(")
    end = s.find(")")
    name = s[start+2:end-1]
    name = name.replace("+", " ")
    return urllib.parse.unquote(name)
    