import taos
import sys
import time
import socket
import os
import threading
import math

from util.log import *
from util.sql import *
from util.cases import *
from util.dnodes import *
from util.common import *
# from tmqCommon import *

class TDTestCase:
    def __init__(self):
        self.vgroups    = 4
        self.ctbNum     = 10
        self.rowsPerTbl = 10000
        self.duraion = '1h'

    def init(self, conn, logSql, replicaVar=1):
        self.replicaVar = int(replicaVar)
        tdLog.debug(f"start to excute {__file__}")
        tdSql.init(conn.cursor(), True)

    def create_database(self,tsql, dbName,dropFlag=1,vgroups=2,replica=1, duration:str='1d'):
        if dropFlag == 1:
            tsql.execute("drop database if exists %s"%(dbName))

        tsql.execute("create database if not exists %s vgroups %d replica %d duration %s"%(dbName, vgroups, replica, duration))
        tdLog.debug("complete to create database %s"%(dbName))
        return

    def create_stable(self,tsql, paraDict):
        colString = tdCom.gen_column_type_str(colname_prefix=paraDict["colPrefix"], column_elm_list=paraDict["colSchema"])
        tagString = tdCom.gen_tag_type_str(tagname_prefix=paraDict["tagPrefix"], tag_elm_list=paraDict["tagSchema"])
        sqlString = f"create table if not exists %s.%s (%s) tags (%s)"%(paraDict["dbName"], paraDict["stbName"], colString, tagString)
        tdLog.debug("%s"%(sqlString))
        tsql.execute(sqlString)
        return

    def create_ctable(self,tsql=None, dbName='dbx',stbName='stb',ctbPrefix='ctb',ctbNum=1,ctbStartIdx=0):
        for i in range(ctbNum):
            sqlString = "create table %s.%s%d using %s.%s tags(%d, 'tb%d', 'tb%d', %d, %d, %d)" % \
                    (dbName,ctbPrefix,i+ctbStartIdx,dbName,stbName,(i+ctbStartIdx) % 5,i+ctbStartIdx,i+ctbStartIdx,i+ctbStartIdx,i+ctbStartIdx,i+ctbStartIdx)
            tsql.execute(sqlString)

        tdLog.debug("complete to create %d child tables by %s.%s" %(ctbNum, dbName, stbName))
        return

    def insert_data(self,tsql,dbName,ctbPrefix,ctbNum,rowsPerTbl,batchNum,startTs,tsStep):
        tdLog.debug("start to insert data ............")
        tsql.execute("use %s" %dbName)
        pre_insert = "insert into "
        sql = pre_insert

        for i in range(ctbNum):
            rowsBatched = 0
            sql += " %s%d values "%(ctbPrefix,i)
            for j in range(rowsPerTbl):
                if (i < ctbNum/2):
                    sql += "(%d, %d, %d, %d,%d,%d,%d,true,'binary%d', 'nchar%d') "%(startTs + j*tsStep, j%10, j%10, j%10, j%10, j%10, j%10, j%10, j%10)
                else:
                    sql += "(%d, %d, NULL, %d,NULL,%d,%d,true,'binary%d', 'nchar%d') "%(startTs + j*tsStep, j%10, j%10, j%10, j%10, j%10, j%10)
                rowsBatched += 1
                if ((rowsBatched == batchNum) or (j == rowsPerTbl - 1)):
                    tsql.execute(sql)
                    rowsBatched = 0
                    if j < rowsPerTbl - 1:
                        sql = "insert into %s%d values " %(ctbPrefix,i)
                    else:
                        sql = "insert into "
        if sql != pre_insert:
            tsql.execute(sql)
        tdLog.debug("insert data ............ [OK]")
        return

    def prepareTestEnv(self):
        tdLog.printNoPrefix("======== prepare test env include database, stable, ctables, and insert data: ")
        paraDict = {'dbName':     'test',
                    'dropFlag':   1,
                    'vgroups':    2,
                    'stbName':    'meters',
                    'colPrefix':  'c',
                    'tagPrefix':  't',
                    'colSchema':   [{'type': 'INT', 'count':1},{'type': 'BIGINT', 'count':1},{'type': 'FLOAT', 'count':1},{'type': 'DOUBLE', 'count':1},{'type': 'smallint', 'count':1},{'type': 'tinyint', 'count':1},{'type': 'bool', 'count':1},{'type': 'binary', 'len':10, 'count':1},{'type': 'nchar', 'len':10, 'count':1}],
                    'tagSchema':   [{'type': 'INT', 'count':1},{'type': 'nchar', 'len':20, 'count':1},{'type': 'binary', 'len':20, 'count':1},{'type': 'BIGINT', 'count':1},{'type': 'smallint', 'count':1},{'type': 'DOUBLE', 'count':1}],
                    'ctbPrefix':  't',
                    'ctbStartIdx': 0,
                    'ctbNum':     100,
                    'rowsPerTbl': 10000,
                    'batchNum':   3000,
                    'startTs':    1537146000000,
                    'tsStep':     600000}

        paraDict['vgroups'] = self.vgroups
        paraDict['ctbNum'] = self.ctbNum
        paraDict['rowsPerTbl'] = self.rowsPerTbl

        tdLog.info("create database")
        self.create_database(tsql=tdSql, dbName=paraDict["dbName"], dropFlag=paraDict["dropFlag"], vgroups=paraDict["vgroups"], replica=self.replicaVar, duration=self.duraion)

        tdLog.info("create stb")
        self.create_stable(tsql=tdSql, paraDict=paraDict)

        tdLog.info("create child tables")
        self.create_ctable(tsql=tdSql, dbName=paraDict["dbName"], \
                stbName=paraDict["stbName"],ctbPrefix=paraDict["ctbPrefix"],\
                ctbNum=paraDict["ctbNum"],ctbStartIdx=paraDict["ctbStartIdx"])
        self.insert_data(tsql=tdSql, dbName=paraDict["dbName"],\
                ctbPrefix=paraDict["ctbPrefix"],ctbNum=paraDict["ctbNum"],\
                rowsPerTbl=paraDict["rowsPerTbl"],batchNum=paraDict["batchNum"],\
                startTs=paraDict["startTs"],tsStep=paraDict["tsStep"])
        return

    def test_partition_by_with_interval_fill_prev_new_group_fill_error(self):
        ## every table has 1500 rows after fill, 10 tables, total 15000 rows.
        ## there is no data from 9-17 08:00:00 ~ 9-17 09:00:00, so first 60 rows of every group will be NULL, cause no prev value.
        sql = "select _wstart, count(*),tbname from meters where ts > '2018-09-17 08:00:00.000' and ts < '2018-09-18 09:00:00.000' partition by tbname interval(1m) fill(PREV) order by tbname, _wstart"
        tdSql.query(sql)
        for i in range(0,10):
            for j in range(0,60):
                tdSql.checkData(i*1500+j, 1, None)

        sql = "select _wstart, count(*),tbname from meters where ts > '2018-09-17 08:00:00.000' and ts < '2018-09-18 09:00:00.000' partition by tbname interval(1m) fill(LINEAR) order by tbname, _wstart"
        tdSql.query(sql)
        for i in range(0,10):
            for j in range(0,60):
                tdSql.checkData(i*1500+j, 1, None)

    def test_fill_with_order_by(self):
        sql = "select _wstart, _wend, count(ts), sum(c1) from meters where ts > '2018-11-25 00:00:00.000' and ts < '2018-11-26 00:00:00.00' interval(1d) fill(NULL) order by _wstart"
        tdSql.query(sql)
        tdSql.checkRows(1)
        sql = "select _wstart, _wend, count(ts), sum(c1) from meters where ts > '2018-11-25 00:00:00.000' and ts < '2018-11-26 00:00:00.00' interval(1d) fill(NULL) order by _wstart desc"
        tdSql.query(sql)
        tdSql.checkRows(1)
        sql = "select _wstart, count(*) from meters where ts > '2018-08-20 00:00:00.000' and ts < '2018-09-30 00:00:00.000' interval(9d) fill(NULL) order by _wstart desc;"
        tdSql.query(sql)
        tdSql.checkRows(6)
        sql = "select _wstart, count(*) from meters where ts > '2018-08-20 00:00:00.000' and ts < '2018-09-30 00:00:00.000' interval(9d) fill(NULL) order by _wstart;"
        tdSql.query(sql)
        tdSql.checkRows(6)

    def test_fill_with_order_by2(self):
        ## window size: 5 minutes, with 6 rows in meters every 10 minutes
        sql = "select _wstart, count(*) from meters where ts >= '2018-09-20 00:00:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(prev) order by _wstart asc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(12)
        tdSql.checkData(0, 1, 10)
        tdSql.checkData(1, 1, 10)
        tdSql.checkData(2, 1, 10)
        tdSql.checkData(3, 1, 10)
        tdSql.checkData(4, 1, 10)
        tdSql.checkData(5, 1, 10)
        tdSql.checkData(6, 1, 10)
        tdSql.checkData(7, 1, 10)
        tdSql.checkData(8, 1, 10)
        tdSql.checkData(9, 1, 10)
        tdSql.checkData(10, 1, 10)
        tdSql.checkData(11, 1, 10)

        sql = "select _wstart, count(*) from meters where ts >= '2018-09-20 00:00:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(prev) order by _wstart desc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(12)
        tdSql.checkData(0, 1, 10)
        tdSql.checkData(1, 1, 10)
        tdSql.checkData(2, 1, 10)
        tdSql.checkData(3, 1, 10)
        tdSql.checkData(4, 1, 10)
        tdSql.checkData(5, 1, 10)
        tdSql.checkData(6, 1, 10)
        tdSql.checkData(7, 1, 10)
        tdSql.checkData(8, 1, 10)
        tdSql.checkData(9, 1, 10)
        tdSql.checkData(10, 1, 10)
        tdSql.checkData(11, 1, 10)

        sql = "select _wstart, count(*) from meters where ts >= '2018-09-20 00:00:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(linear) order by _wstart desc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(12)
        tdSql.checkData(0, 1, None)
        tdSql.checkData(1, 1, 10)
        tdSql.checkData(2, 1, 10)
        tdSql.checkData(3, 1, 10)
        tdSql.checkData(4, 1, 10)
        tdSql.checkData(5, 1, 10)
        tdSql.checkData(6, 1, 10)
        tdSql.checkData(7, 1, 10)
        tdSql.checkData(8, 1, 10)
        tdSql.checkData(9, 1, 10)
        tdSql.checkData(10, 1, 10)
        tdSql.checkData(11, 1, 10)

        sql = "select _wstart, first(ts), last(ts) from meters where ts >= '2018-09-20 00:00:00.000' and ts < '2018-09-20 01:00:00.000' partition by t1 interval(5m) fill(NULL)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(60)

        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(next) order by _wstart asc;"
        tdSql.query(sql, queryTimes=1)
        for i in range(0, 13):
            tdSql.checkData(i, 1, 10)
        tdSql.checkData(13, 1, None)
        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(next) order by _wstart desc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkData(0, 1, None)
        for i in range(1, 14):
            tdSql.checkData(i, 1, 10)

        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(prev) order by _wstart asc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkData(0, 1, None)
        tdSql.checkData(1, 1, None)
        for i in range(2, 14):
            tdSql.checkData(i, 1, 10)
        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(prev) order by _wstart desc;"
        tdSql.query(sql, queryTimes=1)
        for i in range(0, 12):
            tdSql.checkData(i, 1, 10)
        tdSql.checkData(12, 1, None)
        tdSql.checkData(13, 1, None)

        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(linear) order by _wstart asc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkData(0, 1, None)
        tdSql.checkData(1, 1, None)
        for i in range(2, 13):
            tdSql.checkData(i, 1, 10)
        tdSql.checkData(13, 1, None)
        sql = "select _wstart, count(*) from meters where ts >= '2018-09-19 23:54:00.000' and ts < '2018-09-20 01:00:00.000' interval(5m) fill(linear) order by _wstart desc;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkData(0, 1, None)
        for i in range(1, 12):
            tdSql.checkData(i, 1, 10)
        tdSql.checkData(12, 1, None)
        tdSql.checkData(13, 1, None)

    def test_fill_with_complex_expr(self):
        sql = "SELECT _wstart, _wstart + 1d, count(*), now, 1+1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' INTERVAL(5m) FILL(NULL)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(12)
        for i in range(0, 12, 2):
            tdSql.checkData(i, 2, 10)
        for i in range(1, 12, 2):
            tdSql.checkData(i, 2, None)
        for i in range(0, 12):
            firstCol = tdSql.getData(i, 0)
            secondCol = tdSql.getData(i, 1)
            tdLog.debug(f"firstCol: {firstCol}, secondCol: {secondCol}, secondCol - firstCol: {secondCol - firstCol}")
            if secondCol - firstCol != timedelta(days=1):
                tdLog.exit(f"query error: secondCol - firstCol: {secondCol - firstCol}")
            nowCol = tdSql.getData(i, 3)
            if nowCol is None:
                tdLog.exit(f"query error: nowCol: {nowCol}")
            constCol = tdSql.getData(i, 4)
            if constCol != 2:
                tdLog.exit(f"query error: constCol: {constCol}")

        sql = "SELECT _wstart + 1d, count(*), last(ts) + 1a, timediff(_wend, last(ts)) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' INTERVAL(5m) FILL(NULL)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(12)
        for i in range(0, 12, 2):
            tdSql.checkData(i, 1, 10)
            tdSql.checkData(i, 3, 300000)
        for i in range(1, 12, 2):
            tdSql.checkData(i, 1, None)
            tdSql.checkData(i, 2, None)
            tdSql.checkData(i, 3, None)

        sql = "SELECT count(*), tbname FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname INTERVAL(5m) FILL(NULL)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(120)

        sql = "SELECT * from (SELECT count(*), timediff(_wend, last(ts)) + t1, tbname FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) LIMIT 1) order by tbname"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(10)
        j = 0
        for i in range(0, 10):
            tdSql.checkData(i, 1, 300000 + j)
            j = j + 1
            if j == 5:
                j = 0

        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, tbname,t1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) ORDER BY timediff(last(ts), _wstart)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(120)

        sql = "SELECT 1+1, count(*), timediff(_wend, last(ts)) + t1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) HAVING(timediff(last(ts), _wstart)+ t1 >= 1)  ORDER BY timediff(last(ts), _wstart)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(48)

        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) HAVING(timediff(last(ts), _wstart) + t1 >= 1)  ORDER BY timediff(last(ts), _wstart), tbname"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(48)

        sql = "SELECT count(*) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) HAVING(timediff(last(ts), _wstart) >= 0)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(60)

        sql = "SELECT count(*) + 1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(NULL) HAVING(count(*) > 1)"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(0)

        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(value, 0, 0) HAVING(timediff(last(ts), _wstart) + t1 >= 1) ORDER BY timediff(last(ts), _wstart), tbname"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(48)
        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(value, 0, 0) HAVING(count(*) >= 0) ORDER BY timediff(last(ts), _wstart), tbname"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(120)
        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname, t1 INTERVAL(5m) FILL(value, 0, 0) HAVING(count(*) > 0) ORDER BY timediff(last(ts), _wstart), tbname"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(60)
        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname INTERVAL(5m) FILL(linear) HAVING(count(*) >= 0 and t1 <= 1) ORDER BY timediff(last(ts), _wstart), tbname, t1"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(44)
        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname INTERVAL(5m) FILL(prev) HAVING(count(*) >= 0 and t1 > 1) ORDER BY timediff(last(ts), _wstart), tbname, t1"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(72)

        sql = "SELECT 1+1, count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname INTERVAL(5m) FILL(linear) ORDER BY tbname, _wstart;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(120)
        for i in range(11, 120, 12):
            tdSql.checkData(i, 1, None)
        for i in range(0, 120):
            tdSql.checkData(i, 0, 2)

        sql = "SELECT count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1, concat(to_char(_wstart, 'HH:MI:SS__'), tbname) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY tbname INTERVAL(5m) FILL(linear) HAVING(count(*) >= 0) ORDER BY tbname;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(110)
        for i in range(0, 110, 11):
            lastCol = tdSql.getData(i, 3)
            tdLog.debug(f"lastCol: {lastCol}")
            if lastCol[-1:] != str(i//11):
                tdLog.exit(f"query error: lastCol: {lastCol}")

        sql = "SELECT 1+1, count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1,t1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY t1 INTERVAL(5m) FILL(linear) ORDER BY t1, _wstart;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(60)

        sql = "SELECT 1+1, count(*), timediff(_wend, last(ts)) + t1, timediff('2018-09-20 01:00:00', _wstart) + t1,t1 FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY t1 INTERVAL(5m) FILL(linear) HAVING(count(*) > 0) ORDER BY t1, _wstart;"
        tdSql.query(sql, queryTimes=1)
        tdSql.checkRows(55)

        # TODO Fix Me!
        sql = "explain SELECT count(*), timediff(_wend, last(ts)), timediff('2018-09-20 01:00:00', _wstart) FROM meters WHERE ts >= '2018-09-20 00:00:00.000' AND ts < '2018-09-20 01:00:00.000' PARTITION BY concat(tbname, 'asd') INTERVAL(5m) having(concat(tbname, 'asd') like '%asd');"
        tdSql.error(sql, -2147473664) # Error: Planner internal error

    def run(self):
        self.prepareTestEnv()
        self.test_partition_by_with_interval_fill_prev_new_group_fill_error()
        self.test_fill_with_order_by()
        self.test_fill_with_order_by2()
        self.test_fill_with_complex_expr()

    def stop(self):
        tdSql.close()
        tdLog.success(f"{__file__} successfully executed")

event = threading.Event()

tdCases.addLinux(__file__, TDTestCase())
tdCases.addWindows(__file__, TDTestCase())
