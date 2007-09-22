#! /usr/bin/python

from optparse import OptionParser
import os, shutil, tempfile, commands, glob, sys, re

parser = OptionParser()

parser.add_option("-d", "--cd-dir",
                  dest="cddir", default=None,
                  help="The directory of the install cd details")

parser.add_option( "-k", "--gpg-key",
                    dest="gpgkey", default=None, type="string",
                    help="The GPG key used to sign the packages" )

parser.add_option( "--ubuntu-keyring",
                   dest="keyring", default=None, type="string",
                   help="The directory of the ubuntu keyring source. if not provided it will be downloaded." )

parser.add_option( "--indices",
                   dest="indices", default=None, type="string",
                   help="The directory of the ubuntu indices" )
                    

(options, debs) = parser.parse_args()

assert options.cddir is not None
assert options.gpgkey is not None
assert options.indices is not None
assert os.path.isdir( options.indices )

cddir = os.path.abspath( options.cddir )
indices = os.path.abspath( options.indices )

# see what the name of the distro is, (eg dapper, edgy.. )
dists_dir = [ dir for dir in os.listdir( os.path.join ( cddir, 'dists' ) ) if dir not in ['stable', 'unstable' ] ]

assert len(dists_dir) == 1
dist = dists_dir[0]

dist_name_to_version = { 'warty':'4.10', 'hoary':'5.04', 'breezy':'5.10',
                         'dapper':'6.06', 'edgy':'6.10', 'feisty':'7.04',
                         'gusty':'7.10', 'hardy':'8.04' }

assert dist in dist_name_to_version.keys()

def makedir_if_not_exist( *path_parts ):
    path = os.path.join( *path_parts )
    if not os.path.exists( path ):
        os.makedirs( path )

makedir_if_not_exist( cddir, 'dists', dist, 'extras', 'binary-i386' )
makedir_if_not_exist( cddir, 'pool', 'extras' )
makedir_if_not_exist( cddir, 'isolinux' )
makedir_if_not_exist( cddir, 'preseed' )

# Copy all the debs to the extras file
for deb in debs:
    print "Copying %s" % deb
    shutil.copy( deb, os.path.join( cddir, "pool", "extras" ) )

releases_file = open( os.path.join( cddir, 'dists', dist, 'extras', 'binary-i386', 'Release' ), 'w' )
releases_file.write( "Archive: " + dist + "\n" )
releases_file.write( "Version: " + dist_name_to_version[dist] + "\n" )
releases_file.write( "Component: extras\nOrigin: Ubuntu\nLabel: Ubuntu\nArchitecture: i386\n")
releases_file.close()
print "Wrote the Releases file"


old_cwd = os.getcwd()
temp_dir = tempfile.mkdtemp( prefix="camarabuntu-tmp-", dir=old_cwd)
os.chdir( temp_dir )

#shutil.copytree( os.path.join( old_cwd, cddir, 'pool', 'main', 'u', 'ubuntu-keyring' ), temp_dir )
#assert false;


# TODO different versions of ubuntu-keyring
if options.keyring is None:
    # download a new one
    print "Downloading the ubuntu-keyring..."
    status, output = commands.getstatusoutput( "apt-get source ubuntu-keyring" )
    if status != 0:
        print "An error occured when downloading the source of the ubuntu-keyring package"
        print "This is needed to sign our new packages"
        print "The output was:"
        print output
else:
    if options.keyring[-1] == '/':
        # This should be a directory, if there's a / at the end, it'll break os.path.split
        options.keyring = options.keyring[0:-1]
    shutil.copytree( os.path.join( old_cwd, options.keyring ), os.path.join( temp_dir, os.path.split( options.keyring )[1] ) )

# find the file
gpg_keys_filename = glob.glob ( os.path.join( temp_dir, 'ubuntu-keyring*/keyrings/ubuntu-archive-keyring.gpg' ) )[0]
ubuntu_keyring_dir = [name for name in glob.glob( os.path.join( temp_dir, 'ubuntu-keyring*' ) ) if os.path.isdir(name)][0]

assert os.path.isfile( gpg_keys_filename )

print "Adding GPG key %s to the ubuntu-keyring" % options.gpgkey

status, output = commands.getstatusoutput( "gpg --import < %s" % gpg_keys_filename )
# if this fails someone was messing with the code before
assert status == 0

status, output = commands.getstatusoutput( "gpg --export FBB75451 437D05B5 %s > %s" % (options.gpgkey, gpg_keys_filename) )
# Invalid keys are not detected here, unfortunatly
assert status == 0

print "Rebuilding the ubuntu-keyring."
os.chdir( ubuntu_keyring_dir )
status, output =  commands.getstatusoutput( "dpkg-buildpackage -rfakeroot -k%s" % options.gpgkey )
if status != 0:
    print "Unable to rebuild the ubuntu-keyring"
    print "Possible causes:"
    print " (*) The GPG key you gave (%s) is invalid, check available keys with \"gpg --list-keys\"" % options.gpgkey
    print "The output was:"
    print output

# Copy these files into the main component
shutil.copy( glob.glob( os.path.join( temp_dir, "ubuntu-keyring*_all.deb" ) )[0], os.path.join( old_cwd, cddir, 'pool/main/u/ubuntu-keyring/' ) )


# Clean up, remove all this crap
os.chdir( old_cwd )
shutil.rmtree( temp_dir )


## Now create the indices.
temp_dir = tempfile.mkdtemp( prefix="camarabuntu-tmp-", dir=old_cwd )

ftparchive_deb = open( os.path.join( temp_dir, 'apt-ftparchive-deb.conf' ), 'w' )
ftparchive_deb.write( """Dir {
  ArchiveDir "%(cddir)s";
};

TreeDefault {
  Directory "pool/";
};

BinDirectory "pool/main" {
  Packages "dists/%(dist)s/main/binary-i386/Packages";
  BinOverride "%(indices)s/override.%(dist)s.main";
  ExtraOverride "%(indices)s/override.%(dist)s.extra.main";
};

BinDirectory "pool/restricted" {
 Packages "dists/%(dist)s/restricted/binary-i386/Packages";
 BinOverride "%(indices)s/override.%(dist)s.restricted";
};

Default {
  Packages {
    Extensions ".deb";
    Compress ". gzip";
  };
};

Contents {
  Compress "gzip";
};
""" % {'cddir':cddir, 'dist':dist, 'indices':indices} )

ftparchive_deb.close()

# generate the extras override. This is converted from the perl version on
# https://help.ubuntu.com/community/InstallCDCustomization

main_packages = open( os.path.join( old_cwd, cddir, 'dists', dist, 'main/binary-i386/Packages' ) )
extra_overrides = open( os.path.join( temp_dir, "override.%s.extra.main" % dist ), 'w' )
task = None
for line in main_packages:
    line = line.rstrip("\n")
    line = line.rstrip("\r\n")
    line = line.rstrip("\r")
    if re.search("^\s", line):
        continue # to the next line
    if line == "" and task is not None:
        extra_overrides.write("%s Task %s\n" % (package, task))
        package = None
        task = None
    if line == "":
        continue
    key, value = line.split(": ", 1)
    if key == "Package":
        package = value
    if key == "Task":
        task = value


extra_overrides.close()
main_packages.close()

ftparchive_udeb = open( os.path.join( temp_dir, "apt-ftparchive-udeb.conf" ), 'w')
ftparchive_udeb.write("""Dir {
  ArchiveDir "%(cddir)s;
};

TreeDefault {
  Directory "pool/";
};

BinDirectory "pool/main" {
  Packages "dists/%(dist)s/main/debian-installer/binary-i386/Packages";
  BinOverride "%(indices)s/override.%(dist)s.main.debian-installer";
};

BinDirectory "pool/restricted" {
  Packages "dists/%(dist)s/restricted/debian-installer/binary-i386/Packages";
  BinOverride "%(indices)s/override.%(dist)s.restricted.debian-installer";
};

Default {
  Packages {
    Extensions ".udeb";
    Compress ". gzip";
  };
};

Contents {
  Compress "gzip";
};
""" % {'cddir':cddir, 'dist':dist, 'indices':indices} )
ftparchive_udeb.close()

    
