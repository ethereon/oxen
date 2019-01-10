from setuptools import setup, find_packages


def get_long_description():
    with open("README.md", "r") as readme_file:
        return readme_file.read()


setup(
    name='oxen',
    version='0.1.0',
    description='Task runner with a web-based frontend',
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author='Saumitro Dasgupta',
    author_email='sd@cs.stanford.edu',
    url='https://github.com/ethereon/oxen',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: BSD License',
    ],
    packages=find_packages(),
    package_data={
        'oxen': [
            'client/static/js/*.js*',
            'client/static/css/*.css',
            'client/static/templates/*.html',
        ],
    },
    include_package_data=True,
    install_requires=['tornado', 'watchdog'],
    zip_safe=True,
    license='BSD'
)
