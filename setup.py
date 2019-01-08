from setuptools import setup, find_packages

setup(
    name='oxen',
    version='0.1.0',
    description='Task runner with a web-based frontend',
    author='Saumitro Dasgupta',
    author_email='sd@cs.stanford.edu',
    url='https://github.com/ethereon/oxen',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python :: 3.6',
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
    license='MIT'
)
