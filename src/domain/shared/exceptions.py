class DomainException(Exception):
    pass


class UnauthorizedException(DomainException):
    pass


class ForbiddenException(DomainException):
    pass


class NotFoundException(DomainException):
    def __init__(self, entity: str, entity_id: str = ""):
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} no encontrado")


class BusinessRuleException(DomainException):
    pass


class ConflictException(DomainException):
    pass
