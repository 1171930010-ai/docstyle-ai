"""Course server entry; local launcher remains unchanged."""
import os
os.environ['DOCSTYLE_COURSE_MODE']='1'
import server
if __name__=='__main__':
    server.main()
