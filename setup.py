import zipfile
zip_ref = zipfile.ZipFile('OSX.Backdoor.iWorm.zip', 'r')
zip_ref.extractall('.')
zip_ref.close()