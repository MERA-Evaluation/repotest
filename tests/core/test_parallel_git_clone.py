import pytest
import concurrent.futures
import time
import os
import shutil
from repotest.core.docker.python import PythonDockerRepo
from repotest.logger import logger

@pytest.fixture
def cache_folder():
    """Cache folder for parallel clone testing - cleaned before each test"""
    folder = "/tmp/repotest_parallel_test"
    # Remove cache folder if it exists
    if os.path.exists(folder):
        shutil.rmtree(folder)
    yield folder
    # Cleanup after test
    if os.path.exists(folder):
        shutil.rmtree(folder)

@pytest.fixture
def test_repo_list():
    """List of test repositories for parallel clone testing"""
    return [('0b01001001/spectree', 'a091fab020ac26548250c907bae0855273a98778'),
            ('12rambau/sepal_ui', '179bd8d089275c54e94a7614be7ed03d298ef532'),
            ('15five/scim2-filter-parser', '3ed1858b492542d0bc9b9e9ab9547641595e28c1'),
            ('20c/ctl', '879af37647e61767a1ede59ffd353e4cfd27cd6f'),
            ('3YOURMIND/django-migration-linter',
            '799957a5564e8ca1ea20d7cf643abbc21db4e40f'),
            ('4degrees/clique', 'a89507304acce5931f940c34025a6547fa8227b5'),
            ('AI4S2S/lilio', '329a736d26915944744a4235c11497718e0d7832'),
            ('ARMmbed/greentea', '68508c5f4d7cf0635c75399d0ff7cfa896fdf2cc'),
            ('ARMmbed/mbed-tools', '94a3bd761d6ab3305c81da93517767aafff58d7e'),
            ('ARMmbed/yotta', '4094b7a26c66dd64ff724d4f72da282d41ea9fca'),
            ('ASFHyP3/hyp3-sdk', '56cfb700341a0de44ee0f2f3548d5ed6c534d659'),
            ('ASPP/pelita', '557c3a757a24e0f1abe25f7edf5c4ffee83a077e'),
            ('Aarhus-Psychiatry-Research/timeseriesflattener',
            'bb6a7fffb2a520272fcb5d7129957ce22484ff77'),
            ('Abjad/abjad-ext-nauert', '520f389f06e21ee0a094016b4f1e2b0cb58263c1'),
            ('Alexei-Kornienko/schematics_to_swagger',
            '3ddc537a8ed7682e9bb709ebd749b99d7ef09473'),
            ('Algebra8/pyopenapi3', '2237b16747c446adc2b67a080040f222c0493653'),
            ('All-Hands-AI/openhands-aci', 'f9774a3ca86d2ec2430de5dbaef2cf657d48b826'),
            ('All-Hands-AI/openhands-resolver',
            '84ccb9b29d786c3cb16f100b31ee456ddc622fd0'),
            ('ApptuitAI/apptuit-py', '65d256693243562917c4dfd0e8a753781b153b36'),
            ('ArkEcosystem/python-crypto', '1bd016f76b41eba9711be748c1caf20d8042f590'),
            ('AspenWeb/pando.py', '0e0bc40453df28bae014461822fa25daf8263ff8'),
            ('AzureAD/azure-activedirectory-library-for-python',
            'b65cdce996c3e275bf82f1563638150c7ac97034'),
            ('AzureAD/microsoft-authentication-library-for-python',
            'c235d4e9dea9e4954cf0699bd46bb57ddce959be'),
            ('Azure/autorest.python', '4793bd7b9ddc25a241cd54538b4c5750f915b3d2'),
            ('Azure/azure-cli', '62dab24154f910ff7f3ef2b6b3783945b58e9098'),
            ('Azure/azure-functions-durable-python',
            '354ace05d704ae63f9a6488bd6a228adb949e2b2'),
            ('Azure/iotedgedev', 'ce59bad1286bf650d442b2b7fbe16a3db676a497'),
            ('Azure/msrest-for-python', 'c4086bfac4e45b11b6bd4267cff62aa302a51877'),
            ('Azure/msrestazure-for-python', 'bc59bae35d784f0aad8d1e26ebfd9c20897dca46'),
            ('Azure/pykusto', '68121cdd79cc9c1d6b8f71e5e80df566ac6842c7'),
            ('BAMWelDX/weldx', '5aa82b1710fcc85d3bbc1d5d07775ac1828adff6'),
            ('BQSKit/bqskit', '27e209149392231fdaccedfb39ae20b4173c844e'),
            ('BaPSF/bapsflib', '08a56b9001c607982778b16f15a30dd88ba3cf31'),
            ('Bachmann1234/diff_cover', '5f7aeea8b95441f8286a38524ce0234e1716e304'),
            ('Becksteinlab/numkit', 'af05227af13f4bb56f867b026014048f0e3f0454'),
            ('Benardi/touvlo', '0e1ee71ebec9a09370f928dd96d0ae11f3bba404'),
            ('Blaizzy/mlx-vlm', '1e4579ad0c99b41c71f7309a4cb59d0c4e49fca1'),
            ('BoboTiG/ebook-reader-dict', 'd6cc6741d4712018610391f1bc229fb9e0d3210e'),
            ('BrandwatchLtd/api_sdk', '0570363bdee1621b85f8290599e0c86c75bcf802'),
            ('BurnzZ/scrapy-loader-upkeep', '0b36309d1c9ea814e097e06e9d7220cfef6e6f9e'),
            ('CODAIT/exchange-metadata-converter',
            'a5432d877fe947a12c169d2d84c22e034d555289'),
            ('CORE-GATECH-GROUP/serpent-tools',
            '4b93cd86c6149b94960984892dad25de6fbbb41f'),
            ('CS-SI/eodag', 'f7efdd09236091864c16b46822730cf1b97317c9'),
            ('CSCfi/swift-browser-ui', '316d76f77f93701289188d0d461d4fc30fdccf96'),
            ('CartoDB/cartoframes', '86069f44058986062a2af21ef1f6690864784596'),
            ('Ch00k/ffmpy', '69724733ea38cb3ac4bd2c8915c91bf9071d7270'),
            ('Chilipp/autodocsumm', '354e67b443fe212401b1fc0f9e2f0d669c5852c4'),
            ('ClimateImpactLab/impactlab-tools',
            'a56fa03cfe65515c324bfebda79e7906e20ac87d'),
            ('Clinical-Genomics/scout', '8e1c3acd430a1f57f712aac29847e71cac8308f3'),
            ('CodeForPhilly/chime', 'e6ff8aaa0be2be7c27ec9b98611147650d414270')
           ]

def create_repo_instance(repo_name, base_commit, cache_folder):
    """
    Helper function to create a PythonDockerRepo instance which will trigger git clone.
    """
    try:
        repo = PythonDockerRepo(
            repo=repo_name,
            base_commit=base_commit,
            default_cache_folder=cache_folder
        )
        # Clean up the repo after creation
        repo.clean()
        logger.info("%s %s %s"%(repo_name, base_commit, "Ok"))
        return True
    except Exception as e:
        logger.error("%s %s %s %s"%(repo_name, base_commit, "Fail", e))

        print(f"Failed to create repo instance for {repo_name}: {e}")
        return False
    
@pytest.mark.slow
def test_parallel_git_clone(test_repo_list, cache_folder, n_workers=30):
    """
    Test parallel git clone operations to verify the locking mechanism works correctly.
    This test creates multiple PythonDockerRepo instances in parallel to test
    if the git clone locking mechanism prevents race conditions.
    
    To run this test, use: pytest tests/core/docker/test_parallel_git_clone.py --slow
    Note: This test is marked as slow and requires a working internet connection to clone repositories.
    """    
    print("Starting parallel git clone test...")
    start_time = time.time()
    
    # Create multiple instances in parallel
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
        # Submit multiple tasks for the same repo to test locking
        futures = []
        for test_repo in test_repo_list:  # Create 10 parallel instances
            # Use the same repo for all instances to test the locking mechanism
            future = executor.submit(create_repo_instance, test_repo[0], test_repo[1], cache_folder)
            futures.append(future)
        
        # Wait for all tasks to complete
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    end_time = time.time()
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"Test completed in {end_time - start_time:.2f} seconds")
    print(f"Successful clones: {success_count}/{total_count}")
    
    # All operations should succeed if the locking mechanism works correctly
    assert success_count == total_count, f"Expected all {total_count} operations to succeed, but only {success_count} succeeded"
    
    print("All parallel git clone operations completed successfully!")
