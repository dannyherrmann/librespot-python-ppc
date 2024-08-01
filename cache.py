class CacheManager:
    clean_up_threshold = 604800000
    header_hash = 253
    header_timestamp = 254

    def __init__(self, session):
        """
        @Todo Implement function
        :param session:
        """
        self.parent = None