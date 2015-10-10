import scrapy
from scrapy.loader import ItemLoader
from Crawler.items import CSPANItem
import psycopg2
from .transcriber import Transcriber
from selenium import webdriver


#Collect a list of valid candidates from the candidates table in the wsss database. 
conn = psycopg2.connect("dbname=wsss user=wsss")
cur = conn.cursor() 
cur.execute('SELECT fullName from Candidates;')
validCandidates = []
for record in cur:
	validCandidates.append(record[0])
#print validCandidates
print validCandidates[0]
conn.commit()
cur.close()
conn.close()

class CspanSpider(scrapy.Spider):
	name = "cspan"
	allowed_domains = ["c-span.org"]
	start_urls = ["http://www.c-span.org/search/?searchtype=Videos&sort=Most+Recent+Airing&all[]=presidential&all[]=campaign&all[]=speech"]

	def __init__(self):
		self.driver = webdriver.Firefox()


	def parse(self, response):
		#With selenium, click the show more videos button until it is no longer possible to do so. 
		#Then pass that page as the input for the rest of scrapy's activities
		self.driver.get(response.url)

		next = self.driver.find_element_by_id('search-results-limit-100')
		next.click()

		while True:
			try:
				next = self.driver.find_element_by_id('loadmore')
				next.click()
				print "Clicking!"
				
				#This break is a shortcut for Development. Comment out to get more videos
				break
			except:
				break

		print "Scrapy URL is: ", response.url

		
		url = self.driver.current_url

		print "Selenium URL is: ", url

		# with open("seleniumResponse.txt", 'wb') as f:
		# 	f.write(Seleniumresponse.encode('utf-8'))

		

		# filename = response.url.split("/")[-2] + '.html'
		# print filename
		# with open(filename, 'wb') as f:
		# 	f.write(response.body)
		speechLinks = []
		#Extract from the selenium page source instead
		speechLinkElements = self.driver.find_elements_by_xpath('//section/ul/li/a')
		print "Elements list is ", speechLinkElements
		for s in speechLinkElements:
			#print "Attribute is: ", s.get_attribute('href')
			speechLinks.append(s.get_attribute('href'))

		print "Number of Links is: ", len(speechLinks)

		#Extract the links to the search results on the page.
		#speechLinks = response.xpath('//section/ul/li/a/@href').extract()
		# print speechLinks
		# with open("links.txt", 'wb') as f:
		# 	f.write(str(speechLinks))
		print speechLinks

		#Generate a new crawl request for each link followed that treats them as speech videos. 
		for url in speechLinks:
			url = response.urljoin(url)
			yield scrapy.Request(url, callback=self.parse_speech_page)

		self.driver.quit()

	def write_to_db(self, item):
		#Write the item's contents into the database
		conn = psycopg2.connect("dbname=wsss user=wsss")

		cur = conn.cursor()
		cur.execute('INSERT INTO Speeches (url, title, speaker, transcription, collectionTime, speechTime, city, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (item['url'][0], item['title'][0], item['speaker'], item['transcription'][0], item['collectionTime'][0], item['speechTime'][0], item['city'][0], item['state'][0]))

		#Commit queued database transactions and close connection
		conn.commit()
		cur.close()
		conn.close()
		pass

	#Method to validate that the video features a speaker from our candidates list
	#Takes in a list of speakers from a video, returns the first speaker name that matches. If a match does not exist returns None
	def validate_speaker(self, speakers):
		for speaker in speakers:
			if speaker in validCandidates:
				print speaker, "matches!"
				return speaker
			else:
				print speaker, "doesn't match!"
		return None


	#This function handles those pages which are sent as candidates for presidential campaign speeches.
	def parse_speech_page(self, response):
		print response.headers
		print response.url
		
		#Check that this is indeed a video page
		pageType = response.xpath('body/@class').extract()
		print pageType
		if pageType[0] == 'video event':
			print "It's a video!"

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

			# for now, leave the remaining fields blank
			l.add_value('collectionTime', 'null')
			l.add_value('city', 'null')
			l.add_value('state', 'null')

			# call the transcriber class 
			t = Transcriber()
			t.transcribe(response.url, "crawler_test_1")
			speech= t.getSpeech()
			speech_text = speech['speech']
			l.add_value('transcription', speech_text)

			item = l.load_item()

			#Validate that the item contains a speaker we're interested in.
			item['speaker'] = self.validate_speaker(item['speaker'])
			print "speaker is: ", item['speaker']
			
			#Write gathered data to the database
			if item['speaker'] is not None :
				self.write_to_db(item)


		#Call Transcriber class

		#Either add to item to collect as one feed or call insert to database function.


		#Prints the html of the webpage as a text file in current directory. Useful for finding the paths to follow.
		#Use with sublime's reindent feature for easy to follow html
		#pageTitle = response.url.split("/")[-1] + '.html'
		# with open(pageTitle, 'wb') as f:
		# 	f.write(str(response.body))
	# def parse(self, response):
	# 	print response
	# 	print response.url.split("/")
	# 	filename = response.url.split("/")[-1] + '.html'
	# 	print filename
 #        f = open(filename, 'wb')
 #        f.write(response.body)
 #        #f.close()