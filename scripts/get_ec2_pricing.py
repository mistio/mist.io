#!/usr/bin/python
# return a dic with prices for different ec2 providers.
# Uses pricing data from https://github.com/ilia-semenov/awspricingfull

# Specify the csv file with prices and run with
# ./bin/cloudpyt get_ec2_pricing.py


import json, csv
from libcloud.compute.types import Provider

class mydict(dict):
    def __str__(self):
        return json.dumps(self)

csv_file = '/home/user/Desktop/unweb/awspricingfull/EXAMPLE_OUTPUT_AWS_FULL_RI_pricing.csv'

regions = {}

with open(csv_file, 'rb') as csvfile:
    reader = csv.reader(csvfile, delimiter=',')
    for row in reader:
        if row[1] == 'ec2':
            region = row[2]
            size = row[3]
            os = row[6]
            price = row[10]
            if not regions.get(region):
                regions[region] = {}
            if not regions[region].get(size):
                regions[region][size] = {}
            regions[region][size][os] = price

mist_regions = {}
mist_regions[Provider.EC2_EU_WEST] = regions['eu-west-1']
mist_regions[Provider.EC2_SA_EAST] = regions['sa-east-1']
mist_regions[Provider.EC2_AP_NORTHEAST] = regions['ap-northeast-1']
mist_regions[Provider.EC2_AP_SOUTHEAST2] = regions['ap-southeast-2']
mist_regions[Provider.EC2_AP_SOUTHEAST] = regions['ap-southeast-1']
mist_regions[Provider.EC2_US_WEST] = regions['us-west-1']
mist_regions[Provider.EC2_US_WEST_OREGON] = regions['us-west-2']
mist_regions[Provider.EC2_US_EAST] = regions['us-east-1']
mist_regions[Provider.EC2_EU_CENTRAL] = regions['eu-central-1']
mist_regions[Provider.EC2_AP_NORTHEAST2] = regions['ap-northeast-2']
mist_regions[Provider.EC2_AP_NORTHEAST1] = regions['ap-northeast-1']

# formatting for easy copy/paste to mist.io/config.py
for provider in mist_regions:
    print "        \"%s\": {" % provider
    for key in mist_regions[provider].keys()[:-1]:
        print "            \"%s\": %s," % (key, json.dumps(mist_regions[provider][key]))
    key = mist_regions[provider].keys()[-1]
    print "            \"%s\": %s" % (key, json.dumps(mist_regions[provider][key]))
    # don't use a comma for the last key, for valid JSON
    print '        },\n'
