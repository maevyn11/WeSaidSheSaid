from __future__ import print_function
import scrapy
from scrapy.loader import ItemLoader
from Crawler.items import CSPANItem
import psycopg2
import logging
# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait 
# from selenium.webdriver.support import expected_conditions as EC 
import datetime

# How to import the transcriber class from the root directory
import os
import sys
root = os.environ['WSSS_ROOT']
tpath = os.path.join(root, root + '/wesaidshesaid/Transcriber')
sys.path.insert(0,tpath)
# import transcriber
from transcriber import Transcriber

#Collect a list of valid candidates from the candidates table in the wsss database. 
conn = psycopg2.connect("dbname=wsss user=wsss")
cur = conn.cursor() 
cur.execute('SELECT validNames from Candidates;')
validCandidates = []
for record in cur:
	for array in record:
		for name in array:
			# self.logger.debug(name)
			validCandidates.append(name)
#print valid candidates
# self.logger.debug(validCandidates)
conn.commit()
cur.close()
conn.close()

class CspanSpider(scrapy.Spider):
	name = "cspan"
	allowed_domains = ["c-span.org"]
	start_urls = ["http://www.c-span.org/search/?sdate=&edate=&searchtype=Videos&sort=Most+Recent+Airing&text=0&all[]=presidential&all[]=campaign&all[]=speech&show100="]

	def __init__(self):
		### Exterior Print statements moved here for use of logger
		self.logger.debug("root is: " + str(root))
		self.logger.debug("tpath is: " + str(tpath))

	def parse(self, response):
		self.logger.debug("Scrapy URL is: " + str(response.url))
		
		raw_link = "http://www.c-span.org/search/?sdate=&edate=&searchtype=Videos&sort=Most+Recent+Airing&text=0&all[]=presidential&all[]=campaign&all[]=speech&show100=&sdate=&edate=&searchtype=Videos&sort=Most+Recent+Airing&text=0&all[]=presidential&all[]=campaign&all[]=speech&ajax&page="

		num_vids = response.css('.showing').xpath('./text()').extract()[0].rstrip().split(' ')[-1].replace(',','')
		self.logger.debug("number of videos is: " + str(num_vids))
		num_pages = int(int(num_vids)/100)
		#use calculated increment to loop through individual pages of 100 videos
		yield scrapy.Request(response.url, callback=self.parse_links)
		
		for x in range(2,num_pages):
			url = raw_link + str(x)
			yield scrapy.Request(url, callback=self.parse_links)

	def parse_links(self, response):
		#Generate a new crawl request for each link followed that treats them as speech videos. 
		speechLinks = []
		speechLinkElements = response.css(".onevid").xpath("./a/@href").extract()
		self.logger.debug("Elements list is " + str(speechLinkElements))
		for s in speechLinkElements:
			speechLinks.append(s)

		self.logger.debug("Number of Links is: " + str(len(speechLinks)))

		#Extract the links to the search results on the page.
		self.logger.debug(speechLinks)

		for url in speechLinks:
			url = response.urljoin(url)
			yield scrapy.Request(url, callback=self.parse_speech_page)		

	def write_to_db(self, item):

		#Convert collected Speech time to formatted Date
		# item['speechTime'][0]
		#Write the item's contents into the database
		conn = psycopg2.connect("dbname=wsss user=wsss")

		cur = conn.cursor()
		cur.execute('INSERT INTO Speeches (url, title, speaker, transcription, collectionTime, speechTime, city, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (item['url'][0], item['title'][0], item['speaker'], item['transcription'][0], item['collectionTime'][0], item['speechTime'][0], item['city'][0], item['state'][0]))

		#Commit queued database transactions and close connection
		conn.commit()
		cur.close()
		conn.close()
		pass

	def write_stats_to_db(self, url, speaker, result):
		conn = psycopg2.connect("dbname=wsss user=wsss")
		cur = conn.cursor()
		cur.execute('INSERT INTO RunStats (url, speaker, match) VALUES (%s, %s, %s)', (url, speaker, result))

		conn.commit()
		cur.close()
		conn.close()
		pass

	#Method to validate that the video features a speaker from our candidates list
	#Takes in a list of speakers from a video, returns the first speaker name that matches. If a match does not exist returns None
	def validate_speaker(self, item):
		for speaker in item['speaker']:
			if speaker in validCandidates:
				self.write_stats_to_db(item['url'],speaker,True)
				self.logger.debug(str(speaker) + " matches!")
				#Get the standard name for a candidate by looking it up in the candidates table
				fullName = self.normalize_speaker_name(speaker)
				self.logger.debug("fullName grabbed from db is " + str(fullName))
				return fullName
			else:
				self.write_stats_to_db(item['url'],speaker,False)
				self.logger.debug(str(speaker) + " doesn't match!")
		return None


	def normalize_speaker_name(self, speaker):
		conn = psycopg2.connect("dbname=wsss user=wsss")
		cur = conn.cursor()

		#Reference the matched speaker name against the standard fullName stored in the database
		cur.execute('SELECT fullname from Candidates where %s = ANY (validnames);', (speaker,))
		fullName = cur.fetchone()
		self.logger.debug("fullName =" + str(fullName))

		conn.commit()
		cur.close()
		conn.close()

		return fullName[0]

	#This function handles those pages which are sent as candidates for presidential campaign speeches.
	def parse_speech_page(self, response):
		self.logger.debug(response.headers)
		self.logger.debug(response.url)
		
		#Check that this is indeed a video page
		pageType = response.xpath('body/@class').extract()
		self.logger.debug(pageType)
		if pageType[0] == 'video event':
			self.logger.debug("It's a video!")

			#Gather video metadata into a CSPAN Item
			l = ItemLoader(item=CSPANItem(), response=response)

			# gather the name of the speaker(s) in this video by searching for the "filter-transcript" id
			# do not forget to post-process this field by comparing the candidate to the acceptable list from the database !!! 
			l.add_xpath('speaker', "//*[contains(concat(' ', @id, ' '), ' filter-transcript ')]/option[@value and string-length(@value)!=0]/text()")

			# gather the title of the video 
			l.add_xpath('title', "//html/head/meta[@property = 'og:title']/@content")

			# add url to the item loader
			l.add_value('url', response.url)

			# gather the date of the video
			l.add_xpath('speechTime', "//div[@class = 'overview']/span[@class = 'time']/time/text()")

			#Get the current time, and set it for collectionTime
			currentTimestamp = datetime.datetime.now()
			l.add_value('collectionTime', currentTimestamp)
			
			#Get the location of the speech, which is brought in the form City, State, Country
			location = response.xpath("//div[@class = 'video-meta']/div/div[@class = 'details']/div/dl/dt[text() = 'Location:']/following-sibling::dd[1]/text()").extract()

			city, state, country = location[0].split(", ")
			l.add_value('city', city)
			l.add_value('state', state)
			l.add_value('transcription', 'null')

			item = l.load_item()

			#Validate that the item contains a speaker we're interested in.
			item['speaker'] = self.validate_speaker(item)
			self.logger.debug("speaker is: " + str(item['speaker']))
			
			#Write gathered data to the database
			if item['speaker'] is not None :
				# call the transcriber class 
				t = Transcriber()
				t.transcribe(response.url, "crawler_test_1")
				speech= t.getSpeech()
				speech_text = speech['speech']
				speech_text_copy = speech_text
				item['transcription'] = speech_text
				self.write_to_db(item)
				title = item['title'][0]
				title = title.replace(" ", "_")
				filename = title + ".txt"
				self.logger.debug("filename is: " + filename)
				f = open(root + "/wesaidshesaid/speeches/" + filename, 'w')
				f.write(str(speech_text_copy))
				f.close()



		#Call Transcriber class

		#Either add to item to collect as one feed or call insert to database function.


		#Prints the html of the webpage as a text file in current directory. Useful for finding the paths to follow.
		#Use with sublime's reindent feature for easy to follow html
		#pageTitle = response.url.split("/")[-1] + '.html'
		# with open(pageTitle, 'wb') as f:
		# 	f.write(str(response.body))
	# def parse(self, response):
	# 	self.logger.debug(response)
	# 	self.logger.debug(response.url.split("/"))
	# 	filename = response.url.split("/")[-1] + '.html'
	# 	self.logger.debug(filename)
 #        f = open(filename, 'wb')
 #        f.write(response.body)
 #        #f.close()
