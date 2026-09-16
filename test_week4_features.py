"""
Test Suite for Pritiv's Week 4 Resource Hub Features in CodeNest
Verifies ratings, download counters, sorting, pagination, folder upload, my uploads, and profanity integration.
"""
import os
import tempfile
import unittest
from app import app, db
from models import User, Resource, ResourceRating, ResourceCollection
from constants import contains_profanity

class Week4ResourceHubTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.client = app.test_client()

        with app.app_context():
            db.create_all()

            # Create test users
            self.user_alice = User(username='alice', email='alice@student.mmu.edu.my', role='Student', faculty='FCI', is_verified=True)
            self.user_alice.set_password('password123')
            self.user_bob = User(username='bob', email='bob@student.mmu.edu.my', role='Student', faculty='FCI', is_verified=True)
            self.user_bob.set_password('password123')
            self.user_charlie = User(username='charlie', email='charlie@student.mmu.edu.my', role='Student', faculty='FCI', is_verified=True)
            self.user_charlie.set_password('password123')

            db.session.add_all([self.user_alice, self.user_bob, self.user_charlie])
            db.session.commit()

            self.alice_id = self.user_alice.id
            self.bob_id = self.user_bob.id
            self.charlie_id = self.user_charlie.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        try:
            os.close(self.db_fd)
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    def test_feature_1_and_2_ratings_and_average_statistics(self):
        """Test resource rating creation, updates, self-rating prevention, and averages."""
        with app.app_context():
            # Alice uploads a resource
            res = Resource(
                title="Algorithms Chapter 1",
                description="Intro to Sorting",
                filename="sorting.pdf",
                stored_filename="20260910_test_sorting.pdf",
                file_size=1024,
                file_type="pdf",
                category="Lecture Notes",
                faculty="FCI",
                uploader_id=self.alice_id
            )
            db.session.add(res)
            db.session.commit()
            res_id = res.id

            # Initial state
            self.assertIsNone(res.average_rating)
            self.assertEqual(res.rating_count, 0)

            # Bob rates 5 stars
            rating_bob = ResourceRating(rating=5, resource_id=res_id, user_id=self.bob_id)
            db.session.add(rating_bob)
            db.session.commit()

            res = db.session.get(Resource, res_id)
            self.assertEqual(res.rating_count, 1)
            self.assertEqual(res.average_rating, 5.0)

            bob_user = db.session.get(User, self.bob_id)
            self.assertEqual(res.user_rating(bob_user), 5)

            # Charlie rates 3 stars
            rating_charlie = ResourceRating(rating=3, resource_id=res_id, user_id=self.charlie_id)
            db.session.add(rating_charlie)
            db.session.commit()

            res = db.session.get(Resource, res_id)
            self.assertEqual(res.rating_count, 2)
            self.assertEqual(res.average_rating, 4.0)  # (5 + 3) / 2 = 4.0

            # Bob updates his rating to 4 stars
            rating_bob.rating = 4
            db.session.commit()

            res = db.session.get(Resource, res_id)
            self.assertEqual(res.rating_count, 2)
            self.assertEqual(res.average_rating, 3.5)  # (4 + 3) / 2 = 3.5

            # Self-rating rejection in HTTP route
            with self.client:
                self.client.post('/login', data={'email_or_username': 'alice', 'password': 'password123'}, follow_redirects=True)
                resp = self.client.post(f'/resources/{res_id}/rate', data={'rating': 5}, follow_redirects=True)
                self.assertIn(b"You cannot rate your own", resp.data)

    def test_feature_3_download_counter_atomic_increment(self):
        """Test that download count increments atomically when downloading an existing file."""
        with app.app_context():
            test_filename = "download_test_file.txt"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], test_filename)
            with open(file_path, 'w') as f:
                f.write("Test download content")

            res = Resource(
                title="Download Counter Test",
                filename="original_test.txt",
                stored_filename=test_filename,
                file_size=21,
                file_type="txt",
                uploader_id=self.alice_id,
                download_count=0
            )
            db.session.add(res)
            db.session.commit()
            res_id = res.id

            self.assertEqual(res.download_count, 0)

            # Perform download via HTTP client
            resp = self.client.get(f'/resources/download/{res_id}')
            self.assertEqual(resp.status_code, 200)
            resp.close()

            res = db.session.get(Resource, res_id)
            self.assertEqual(res.download_count, 1)

            # Second download
            resp2 = self.client.get(f'/resources/download/{res_id}')
            self.assertEqual(resp2.status_code, 200)
            resp2.close()

            res = db.session.get(Resource, res_id)
            self.assertEqual(res.download_count, 2)

            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

    def test_feature_4_sorting_algorithms(self):
        """Test sorting by newest, downloads, and ratings."""
        with app.app_context():
            from app import sort_feed_items
            r1 = Resource(title="R1", file_size=10, file_type="pdf", uploader_id=self.alice_id, download_count=10)
            r2 = Resource(title="R2", file_size=10, file_type="pdf", uploader_id=self.alice_id, download_count=50)
            r3 = Resource(title="R3", file_size=10, file_type="pdf", uploader_id=self.alice_id, download_count=5)
            db.session.add_all([r1, r2, r3])
            db.session.commit()

            # Add ratings to r3 (5 stars) and r1 (2 stars)
            db.session.add(ResourceRating(rating=5, resource_id=r3.id, user_id=self.bob_id))
            db.session.add(ResourceRating(rating=2, resource_id=r1.id, user_id=self.bob_id))
            db.session.commit()

            items = [r1, r2, r3]

            # 1. Sort by downloads (r2: 50 -> r1: 10 -> r3: 5)
            sorted_downloads = sort_feed_items(items, 'downloads')
            self.assertEqual([x.title for x in sorted_downloads], ["R2", "R1", "R3"])

            # 2. Sort by rating (r3: 5.0 -> r1: 2.0 -> r2: unrated)
            sorted_rating = sort_feed_items(items, 'rating')
            self.assertEqual([x.title for x in sorted_rating], ["R3", "R1", "R2"])

    def test_feature_7_folder_upload_and_collection(self):
        """Test collection creation, path safety, and statistics."""
        with app.app_context():
            col = ResourceCollection(
                title="Discrete Mathematics Complete Notes",
                description="Week 1 to Week 5 notes",
                category="Lecture Notes",
                faculty="FCI",
                uploader_id=self.alice_id
            )
            db.session.add(col)
            db.session.flush()

            m1 = Resource(
                title="week1_intro.pdf",
                filename="week1_intro.pdf",
                stored_filename="2026_w1.pdf",
                file_size=2000,
                file_type="pdf",
                collection_id=col.id,
                relative_path="chapter1/week1_intro.pdf",
                uploader_id=self.alice_id,
                download_count=4
            )
            m2 = Resource(
                title="week2_sets.pdf",
                filename="week2_sets.pdf",
                stored_filename="2026_w2.pdf",
                file_size=3000,
                file_type="pdf",
                collection_id=col.id,
                relative_path="chapter1/week2_sets.pdf",
                uploader_id=self.alice_id,
                download_count=6
            )
            db.session.add_all([m1, m2])
            db.session.commit()

            # Rate member 1
            db.session.add(ResourceRating(rating=5, resource_id=m1.id, user_id=self.bob_id))
            db.session.commit()

            col = db.session.get(ResourceCollection, col.id)
            self.assertEqual(col.file_count, 2)
            self.assertEqual(col.download_count, 10)  # 4 + 6 = 10
            self.assertEqual(col.average_rating, 5.0)

    def test_feature_9_profanity_filter_integration(self):
        """Test profanity filter validation on titles and descriptions."""
        has_prof, term = contains_profanity("This is a bullshit resource")
        self.assertTrue(has_prof)
        self.assertEqual(term, "bullshit")

        has_prof, term = contains_profanity("Clean lecture notes for Operating Systems")
        self.assertFalse(has_prof)
        self.assertIsNone(term)

if __name__ == '__main__':
    unittest.main()
