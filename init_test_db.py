import sqlite3

con = sqlite3.connect("birthdayparty.db")

cur = con.cursor()

cur.execute("""CREATE TABLE user(
	userid INTEGER PRIMARY KEY AUTOINCREMENT,
	username TEXT UNIQUE NOT NULL,
	usertoken TEXT NOT NULL,
	userdpcount INTEGER NOT NULL DEFAULT 0
)""")
# userdpcount in theory stays the same as COUNT(*) FROM dp WHERE dpuserid=userid,
# but that's a relatively expensive query so we track it separately
# (maybe it would be fine if we indexed on dpuserid?)

# this is the really big table that stores found DPs
cur.execute("""CREATE TABLE dp(
	dpid INTEGER PRIMARY KEY AUTOINCREMENT,
	dpuserid INTEGER NOT NULL,
	dpstart BLOB NOT NULL,
	dpend BLOB NOT NULL,
	dptime INTEGER NOT NULL,
	FOREIGN KEY(dpuserid) REFERENCES user(userid)
)""")

cur.execute("CREATE INDEX hashend ON dp(dpend);")
cur.execute("CREATE INDEX hashtime ON dp(dptime);") # for listing most recent finds

# separate table for keeping track of recently found DPs
# used to calculate hashrate stats without needing to search thru the whole dp table
cur.execute("""CREATE TABLE recent(
	rid INTEGER PRIMARY KEY AUTOINCREMENT,
	rdpid INTEGER NOT NULL,
	FOREIGN KEY(rdpid) REFERENCES dp(dpid)
)""")

cur.execute("""CREATE TABLE collision(
	collid INTEGER PRIMARY KEY AUTOINCREMENT,
	colldpidone INTEGER NOT NULL,
	colldpidtwo INTEGER NOT NULL,
	FOREIGN KEY(colldpidone) REFERENCES user(dpid),
	FOREIGN KEY(colldpidtwo) REFERENCES user(dpid)
)""")

cur.execute("INSERT INTO user (username, usertoken) VALUES (?, ?)", ("retr0id", "foobar"))
cur.execute("INSERT INTO user (username, usertoken) VALUES (?, ?)", ("somebody", "foobar"))
cur.execute("INSERT INTO user (username, usertoken) VALUES (?, ?)", ("hello", "foobar"))

con.commit()
